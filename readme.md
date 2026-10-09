# Agent Harness —— 从零手写一个最小可用 Agent

> 不依赖任何 Agent 框架（LangChain / LangGraph / OpenHands 等），只用 `openai` SDK 直连 DeepSeek，从零实现一个最小可用 Agent。目的是彻底搞懂 **"Agent 到底是怎么转起来的"**。

## 它能做什么

- **4 个工具**：计算器（calculator）、搜索（search，mock）、天气（weather，mock）、待办（todo，有状态）
- **工具注册机制**：每个工具有 name / description / 参数 Schema，LLM 基于 Schema 自主决策
- **Agent 主循环**：用户输入 → LLM 判断"直接回复还是调工具" → 执行工具 → 结果喂回 → 循环，直到出最终答案
- **Session 隔离**：多个窗口（session_id）互不影响、可随时接续、支持"纯对话追问"和"带工具的追问"
- **Context 管理**：最大轮次限制 + 超长历史的基础压缩
- **健壮性**：基本异常处理 + 工具调用 trace 日志
- **测试**：11 个 pytest 用例

---

## 核心概念（学习资料）

### 1. 工具注册机制

**问题**：LLM 怎么知道"有哪些工具、每个工具要什么参数"？

**做法**：建一个"工具花名册"，每个工具登记 4 样东西：

```python
TOOLS[name] = {
    "name": name,            # 工具名
    "description": description,   # 干嘛的（给 LLM 看）
    "parameters": parameters,     # 参数说明书 / JSON Schema（给 LLM 看）
    "func": func,                 # 真正干活的函数（给程序用）
}
```

- `description` 和 `parameters`（JSON Schema）是**给 LLM 读的说明书**——它靠这份说明书决定"该不该调这个工具、传什么参数"。说明书写糊了，LLM 就选错工具。
- `func` 是**给程序用的函数本体**。
- 加新工具 = 写个函数 + `register_tool(...)` 登记一次，别的代码一行不用改。

`get_tools()` 负责把扁平的花名册"翻译"成 OpenAI SDK 要的嵌套格式（外面包一层 `{"type": "function", "function": {...}}`）。

### 2. Agent 主循环

一个 `for` 循环 + 一个 `if` 判断，就是 Agent 的灵魂：

```python
for _ in range(MAX_ROUNDS):
    response = client.chat.completions.create(messages=..., tools=get_tools())
    msg = response.choices[0].message

    if msg.tool_calls:
        # LLM 想调工具 → 执行工具 → 把结果作为 role="tool" 消息喂回 → 继续循环
        ...
    else:
        # LLM 不再调工具 → 这就是最终答案
        return msg.content
```

关键点：

- LLM 要调工具时，`content` 是空的，工具调用信息在 `msg.tool_calls` 里（含 `id`、`function.name`、`function.arguments`）。
- `arguments` 是 **JSON 字符串**，要 `json.loads(...)` 转成字典，再 `func(**args)` 执行。
- 把结果喂回去要用 `role="tool"` 消息，并带上 `tool_call_id`（LLM 靠它知道"这结果回答哪次调用"）。
- 用 `for` 代替 `while True` 是为了给循环加上限，防止 LLM 一直调工具导致死循环。

### 3. Session 隔离

**问题**：窗口 1 和窗口 2 要互相独立、各自能接续。

**做法**：用字典按 `session_id` 分开存：

```python
SESSIONS = {}   # session_id -> {"messages": [...]}

def get_session(session_id):
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"messages": [system提示]}
    return SESSIONS[session_id]
```

- 每个 session 有自己的**历史**（messages）和自己的**待办状态**。
- 工具的"有状态"（todo）也按 session 隔离：用一个 `CURRENT_SESSION` 上下文变量，agent 执行工具前先设置它，工具读它就知道该动哪份待办。
- **LLM 决定业务参数（city/expression/item），harness 决定上下文（session_id）**——后者不该让 LLM 决定。

### 4. Context 管理

- **最大轮次**：`MAX_ROUNDS = 5`，限制工具调用轮数，防死循环。
- **基础压缩**：消息超过 `MAX_MESSAGES` 时，只保留 `system 提示 + 最近 N 条`：

```python
return [messages[0]] + messages[-(MAX_MESSAGES - 1):]
```

- 塞进 context 的：system 提示、用户输入、LLM 的 tool_calls、工具结果、最终答案。
- **不塞**的：`reasoning_content`（思考过程）——它是一次性内部推理，下一轮用不上，塞进去浪费。

### 5. 健壮性（异常处理 + 日志）

- **日志（trace）**：每次调工具前后打印 `[TRACE] 调用工具 X，参数: ...` / `[TRACE] X 返回: ...`，出问题时能还原"程序干了啥"。
- **异常处理**：`json.loads`、`func(**args)`、调 LLM 三处都可能炸，用 `try/except Exception as e` 兜住。
- **关键思路**：工具执行出错时**不崩**，而是把错误信息当"工具结果"喂回 LLM，让 LLM 看到错误自己想办法（重试或告诉用户）。

---

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置

在项目目录新建 `.env` 文件，写入（**此文件不要提交到 git**）：

```
DEEPSEEK_API_KEY=你的DeepSeek密钥
```

### 运行

```bash
uvicorn server:app --reload
```

浏览器打开 http://127.0.0.1:8000/docs ，在 `/chat` 接口里填：

```json
{"message": "帮我记个待办：明天开会", "session_id": "w1"}
```

### 测试

```bash
python -m pytest -v
```

---

## 项目结构

| 文件 | 作用 |
|---|---|
| `tools.py` | 4 个工具函数 + 注册机制（TOOLS / register_tool / get_tools）|
| `agent.py` | 主循环 + session 隔离 + context 管理 + 异常处理 + trace 日志 |
| `server.py` | FastAPI 接口，把 agent 暴露成 Web 服务 |
| `test_agents.py` | 11 个 pytest 测试用例 |
| `requirements.txt` | 依赖清单 |
| `.env` | 密钥（不入 git）|

---

## 我踩过的坑（学习记录）

> 每个坑都是真实报错、真实排查。记下来比看十篇教程都有用。

1. **改完代码忘了保存就运行** —— 终端跑的是硬盘上的旧版本，输出跟预期不符。教训：**改完先 Ctrl+S 再运行**。

2. **环境变量名写错** —— 写了 `os.getenv("OPENAI_API_KEY")`，但 `.env` 里存的是 `DEEPSEEK_API_KEY`，拿到 `None`，报 `OpenAIError: The api_key client option must be set`。教训：`os.getenv()` 里的名字必须跟 `.env` 里 `=` 左边**一字不差**。

3. **用了危险的 `eval`** —— 计算器最初用 `eval()` 执行表达式，有任意代码执行风险，换成 `simpleeval` 的 `simple_eval`。教训：**别用 `eval` 处理不可信输入**。

4. **import 了却没调用** —— 写了 `from simpleeval import simple_eval`，但函数里还在调 `eval()`。教训：import 只是"把东西搬进来"，还得真正去调用它。

5. **字符串漏引号** —— JSON Schema 里写 `"type":object`（漏了引号），`object` 变成了 Python 内置类。当时能跑，发给 LLM 序列化时才炸。教训：JSON 里 `"type"` 的值必须是字符串 `"object"`，要加引号。

6. **拼写错 + 只改一半** —— `parameters` 写成了 `paraters`，三处只改了两处，剩下一处字典键名没改，后面 `t["parameters"]` 就 KeyError。教训：**一个名字多处使用，改名必须全部改**。

7. **`dict + list` 类型错误** —— `trim_messages` 里写了 `messages[0] + messages[-19:]`（字典 + 列表），正确写法是 `[messages[0]] + messages[-19:]`。这个 bug 手动测从没暴露（对话都太短，没触发压缩分支），是 **pytest 用 30 条消息把它逼出来的**。教训：**测试能覆盖手动测不到的边界分支**。

8. **换数据结构只改了一半** —— 要用 `dict.setdefault`，但 `TODOS` 还声明成 `[]`（list），报 `AttributeError: 'list' object has no attribute 'setdefault'`。教训：换类型时，声明处也要一起改。

9. **类名对不上** —— 定义了 `class AskRequest`，接口里却写 `data:ChatIn`，报 `NameError: name 'ChatIn' is not defined`。教训：改类名要两处一起改。

10. **模型名凭旧印象** —— 一开始以为只有 `deepseek-chat`、`deepseek-flash` 不存在，后来看官方文档发现 `deepseek-flash` 是有效的推理模型。教训：**以官方文档为准，别凭旧印象**。

11. **进程生命周期误解** —— 困惑"为什么历史条数一直是 5"：每次 `python -c` 都是**新进程**，内存里的 `SESSIONS`/`TODOS` 进程一退出就清空。教训：**内存状态的生命周期 = 进程生命周期**；要跨请求保留状态，需要常驻服务（FastAPI）或持久化存储。

---

## 技术栈

- Python 3.11 / FastAPI / uvicorn
- openai SDK（直连 DeepSeek）
- simpleeval（安全数学表达式求值）
- pytest（测试）
