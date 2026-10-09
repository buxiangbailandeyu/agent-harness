# 从零手写一个 Agent：不碰 LangChain，我搞懂了 Agent 是怎么转起来的

> 本文写给「会一点 Python、对 AI 感兴趣、但还没真正写过 Agent」的读者。不假设你懂任何框架。

---

## 一、为什么不直接用框架

现在一搜「Agent 教程」，十篇里有九篇是 LangChain、LangGraph、AutoGPT。它们确实好用，但有个致命问题：**你会「用」，却不懂「为什么」**。出了 bug，你对着层层封装的 API 干瞪眼，不知道黑盒里到底发生了什么。

于是我反着来：**不碰任何框架，只用 `openai` SDK 直连 DeepSeek，从零写一个最小可用的 Agent**。

写完才发现，Agent 的内核小得惊人——**核心循环只有十几行**。剩下的全是工程活：会话隔离、上下文管理、持久化、异常处理、前端、流式输出。

这篇文章把我亲手踩过的坑、悟出来的道理，全部写下来。

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

整个过程就四步：

1. 把「用户输入 + 历史 + 工具说明书」一起发给 LLM。
2. LLM 判断：**直接回答**，还是**调用某个工具**？
3. 如果调工具，就执行，把结果作为一条新消息喂回去，回到第 1 步。
4. 直到 LLM 说「不用再调了」，输出最终答案。

**LLM 是大脑，循环是心跳。** 这就是 Agent 的全部骨架。剩下的所有代码，都是在给这个骨架加肌肉。

---

## 三、四个零件

### 1. 工具注册：给 LLM 一份「说明书」

LLM 怎么知道有哪些工具、每个工具要什么参数？答案是 **JSON Schema**。每个工具登记一份说明书：

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

LLM 靠这份说明书自己决定「该不该调、传什么参数」。**说明书写糊了，LLM 就会选错工具**——这是调 Agent 最容易被忽略的一环。很多人 agent 表现差，第一件事就该回来检查工具描述写得清不清楚。

### 2. Session 隔离：每个窗口各记各的账

多个对话窗口要互相独立、各自能接续。做法就是按 `session_id` 分字典存历史。这里有一条我悟出的重要原则：

> **业务参数（城市、表达式、待办内容）让 LLM 决定，但上下文（session_id）由程序决定**，绝不能丢给 LLM。

session_id 是「哪个人、哪段对话」的问题，属于程序的职责，不是 LLM 该管的。

### 3. Context 管理：别把上下文撑爆

每轮对话都会往上下文里塞东西，塞满了会又慢又贵。最小做法：

- **限制最大轮次**（防 LLM 一直调工具死循环）；
- **超长历史只保留「system 提示 + 最近 N 条」**；
- 模型的「思考过程」（`reasoning_content`）是内部一次性推理，**不要**塞进上下文，纯浪费。

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

浏览器里的 JS 用 `fetch` 发 POST 请求到后端，拿到数据后 `createElement` 动态生成气泡。这里有个安全细节：用户输入要用 `textContent` 写，而不是 `innerHTML`，否则用户输入的内容可能被当成代码执行（XSS）。

---

## 六、进阶：让回复「流式」出来（SSE）

做完基础版后，有个体验问题特别明显：发一句话，得**干等好几秒**，整段答案才一次性蹦出来。能不能像 ChatGPT 那样，**一个字一个字往外吐**？

这就是**流式输出**，用的技术叫 SSE（Server-Sent Events，服务器推送事件）。做完这步，我才真正理解了「响应」和「流」的区别。

### 1. 流式的本质 = 生成器 + `yield`

普通函数是 `return`——算完、一次性全给你。流式函数是 `yield`——算出一个字，立刻吐一个字：

```python
def ask_stream(user_text, session_id="default"):
    stream = client.chat.completions.create(
        model="deepseek-flash", messages=..., tools=..., stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content    # 每 yield 一次，前端就收到一片
```

FastAPI 的 `StreamingResponse` 拿到这个生成器，`yield` 什么就立刻发什么，**不用等结束**。这就是「打字机效果」的来源。

### 2. SSE 的帧格式：`data: {json}\n\n`

服务器和浏览器之间怎么约定「一片」的边界？SSE 的规定是：每个事件之间用**空行**分隔，每条数据都以 `data:` 开头：

```
data: {"token": "我是"}

data: {"token": "你的"}

data: [DONE]
```

结尾发一个 `data: [DONE]` 当「结束信号」。前端就靠空行把流切成一条条事件。

### 3. 前端读流和读普通 JSON 完全不一样

普通请求是 `await resp.json()`——等响应**完整**了再解析。但流式响应从头到尾都不会「完整」，所以得换一种读法：

```js
const reader = resp.body.getReader();   // 拿读取器
const decoder = new TextDecoder();
let buf = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  buf += decoder.decode(value, { stream: true });
  // 按 "\n\n" 切事件，逐片追加到气泡
}
```

### 4. 流式里最容易写错的地方

这是整篇最值得记的一课：**工具调用的参数在流式里是分片到的**。

普通响应里，`tool_calls` 是一个完整对象。但流式里，`id`、`name`、`arguments` 都是**碎片**，分好几块到达，用 `index`（第几个工具）来标识。必须按 `index` 归组、用 `+=` 拼接，而不是覆盖：

```python
t = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
if tc.function and tc.function.arguments:
    t["arguments"] += tc.function.arguments   # 碎片要拼起来，不能覆盖
```

我第一次就是在这里翻车的——参数只拼到最后一片，`json.loads` 直接失败。这个细节，教程里很少讲清楚。

---

## 七、测试：mock 掉外部世界

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

## 八、我踩过最值得分享的几个坑

1. **拼写错 + 只改一半**：`parameters` 写成 `paraters`，三处只改两处，剩下一处 KeyError。改名必须全局搜一遍。

2. **写了函数却没调用**：`msg_to_dict` 写对了，但调用处还是用原始对象；`save_sessions`/`load_sessions` 写对了，却一个都没接线。**函数要被人调用才生效**。

3. **`<script>` 放在了元素出生前**：浏览器「边读边执行」，脚本在 `<head>` 里找按钮时，按钮还没被读到，返回 `null`。脚本要放在它操作的元素之后。

4. **拼写错藏在 `except` 里**：`save` 拼成 `sava`，正常路径不经过它、测试也发现不了；直到真出错了，才在错误处理里又爆一个 `NameError`，把真正的错误信息盖住。**错误处理代码最该多测，因为平时跑不到。**

5. **别用 `eval` 执行不可信输入**：计算器最初用 `eval()`，有任意代码执行风险，换成了 `simpleeval`。

6. **`dict + list` 类型错误**：`trim_messages` 里写了 `messages[0] + messages[-19:]`（字典加列表），正确写法是 `[messages[0]] + ...`。这个 bug 手动测从没暴露（对话都太短），是**测试用 30 条消息把它逼出来的**。

---

## 九、结语

这个项目最后能跑，靠的不是什么高深技术，而是**把每个零件都亲手写过、踩过、修过**。从十几行的循环，到 SQLite 分层、前端页面、流式输出、测试覆盖——每一步都只往前推一点，但回头看，它已经是个真正的、属于我自己的 Agent。

框架帮你省时间，但省掉的那部分，恰恰是理解它到底在干什么的关键。

如果你也想彻底搞懂 Agent，我的建议还是那句：**先别碰框架，自己写一遍。** 一个循环 + 四个零件 + 一份测试 + 一个流式，就能搭起一个真正属于你的 Agent。

完整代码结构和每个坑的细节，都在项目的 `README.md` 里。
