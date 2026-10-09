# 从零手写一个 Agent：不碰 LangChain，我终于搞懂了「Agent 到底是怎么转起来的」

> 这是一篇面向「会点 Python、对 AI 感兴趣、但还没写过 Agent」的读者的文章。

---

## 一、为什么不直接用框架

现在提到 Agent，教程里十有八九是 LangChain、LangGraph、AutoGPT。它们很好用，但有个问题：**你「会用」，却不「懂」**。出了 bug，你对着层层封装的 API 干瞪眼，不知道里面发生了什么。

我决定反过来：**不碰任何框架，只用 `openai` SDK 直连 DeepSeek，从零写一个最小可用的 Agent**。写完发现，Agent 的内核小得让人意外——核心循环其实只有十几行。剩下的全是工程：会话隔离、上下文管理、持久化、异常处理。

这篇文章把我踩的坑和悟出的东西都写下来。

---

## 二、Agent 的本质：一个循环 + 一个判断

很多人把 Agent 想得很玄。拆开看，它的灵魂就是一个带次数上限的 `for` 循环：

```python
for _ in range(MAX_ROUNDS):
    response = client.chat.completions.create(messages=..., tools=get_tools())
    msg = response.choices[0].message

    if msg.tool_calls:
        # LLM 想调工具 → 执行工具 → 把结果喂回去 → 再问一次
        ...
    else:
        # LLM 不调工具了 → 这就是最终答案
        return msg.content
```

整个过程：

1. 把「用户输入 + 历史 + 工具说明书」一起发给 LLM。
2. LLM 判断：是**直接回答**，还是**调用某个工具**？
3. 如果调工具，就执行，把结果作为一条新消息喂回去，回到第 1 步。
4. 直到 LLM 说「不用再调了」，输出最终答案。

**LLM 是大脑，循环是心跳。** 这就是 Agent 的全部骨架。

---

## 三、四个零件

### 1. 工具注册：给 LLM 一份「说明书」

LLM 怎么知道有哪些工具、每个工具要什么参数？答案是 **JSON Schema**。每个工具登记一份「说明书」：

```python
{
    "name": "weather",
    "description": "查询某城市的天气。",
    "parameters": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名"}},
        "required": ["city"],
    },
}
```

LLM 靠这份说明书自己决定「该不该调、传什么参数」。**说明书写糊了，LLM 就会选错工具**——这是调 Agent 最容易被忽略的一环。

### 2. Session 隔离：每个窗口各记各的账

多个对话窗口要互相独立、各自能接续。做法就是按 `session_id` 分字典存历史。关键原则：**业务参数（城市、表达式、待办内容）让 LLM 决定，但上下文（session_id）由程序决定**，绝不能丢给 LLM。

### 3. Context 管理：别把上下文撑爆

每轮对话都会往上下文里塞东西，塞满了会又慢又贵。最小做法：限制最大轮次（防死循环）+ 超长历史只保留「system 提示 + 最近 N 条」。另外，模型的「思考过程」（reasoning_content）是内部一次性推理，**不要**塞进上下文，纯浪费。

### 4. 异常处理：出错不崩，把错误喂回去

工具执行可能出错（网络超时、参数不对）。原则是**不让程序崩**，而是把错误信息当成工具结果喂回 LLM，让它看到错误自己想办法。再配一个 `[TRACE]` 日志，出问题时能还原「程序到底干了啥」。

---

## 四、持久化：从 JSON 到 SQLite 的分层

第一个版本我用 JSON 文件存会话，重启能读回来，记忆不丢。但更专业的做法是把「跟数据库打交道」的部分抽成独立的**数据访问层**（`db.py`），用 Python 自带的 `sqlite3`：

- `messages`、`todos` 两张表，都有 `session_id` 和 `created_at`。
- 工具调用信息（`tool_calls`）是嵌套结构，SQLite 存不了，就 `json.dumps` 存成字符串、读时 `json.loads` 还原。
- 业务代码只调 `db.append_message(...)` 这种接口，**以后想换 MySQL/Redis，只改 `db.py`**。

顺带一个后端基本功：SQL 里一定要用 `?` 占位符传值（参数化查询），**别用字符串拼接拼 SQL**，否则就是 SQL 注入漏洞。

---

## 五、前端：一个单文件就够

前端我没引任何框架，一个 `index.html`（内嵌 CSS + JS）搞定聊天界面：聊天气泡、加载态、会话切换、自动滚动、回车发送。

浏览器里的 JS 用 `fetch` 发 POST 请求到后端 `/chat`，拿到 JSON 后 `createElement` 动态生成气泡。这里有个安全细节：用户输入要用 `textContent` 写，而不是 `innerHTML`，否则用户输入的内容可能被当成代码执行（XSS）。

---

## 六、测试：mock 掉外部世界

写完功能不算完，测试才是让项目「敢改」的底气。我学到最有价值的一招是 **mock**：

真实调 GitHub / 天气 API 有三大问题——慢、要联网、结果会变（flaky）。所以测试时用 `monkeypatch` 把 `requests.get` 换成「替身」，返回写死的数据：

```python
def test_weather(monkeypatch):
    class Faker:
        def raise_for_status(self): pass
        text = "北京: ✨ +20°C"
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: Faker())
    assert "北京" in tools.weather("北京")
```

测试只该测**你自己的代码**，不该测**别人的服务器今天在不在线**。

---

## 七、我踩过最值得分享的几个坑

1. **拼写错 + 只改一半**：`parameters` 写成 `paraters`，三处只改两处，剩下一处 KeyError。改名字必须全局搜一遍。

2. **写了函数却没调用**：`msg_to_dict` 写对了，但调用处还是用原始对象；`save_sessions`/`load_sessions` 写对了，却一个都没接线。**函数要被人调用才生效**。

3. **`<script>` 放在了元素出生前**：浏览器「边读边执行」，脚本在 `<head>` 里找按钮时，按钮还没被读到，返回 `null`。脚本要放在它操作的元素之后。

4. **拼写错藏在 `except` 里**：`save` 拼成 `sava`，正常路径不经过它，测试也发现不了；直到真出错了，才在错误处理里又爆一个 `NameError`，把真正的错误信息盖住。**错误处理代码最该多测，因为平时跑不到。**

5. **别用 `eval` 执行不可信输入**：计算器最初用 `eval()`，有任意代码执行风险，换成了 `simpleeval`。

---

## 八、结语

这个项目最后能跑，靠的不是什么高深技术，而是**把每个零件都亲手写过、踩过、修过**。框架帮你省时间，但省掉的那部分，恰恰是理解它到底在干什么的关键。

如果你也想彻底搞懂 Agent，我的建议是：**先别碰框架，自己写一遍。** 十几行的循环 + 四个零件 + 一份测试，就能搭起一个真正属于你自己的 Agent。

完整代码结构和每个坑的细节，都在项目的 `README.md` 里。
