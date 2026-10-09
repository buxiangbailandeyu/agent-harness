# Agent Harness —— 从零手写一个最小可用 Agent

> 不依赖任何 Agent 框架（LangChain / LangGraph / OpenHands 等），只用 `openai` SDK 直连 DeepSeek，从零实现一个最小可用 Agent。目的是彻底搞懂 **「Agent 到底是怎么转起来的」**。

## 它能做什么

- **4 个工具**：计算器（calculator）、搜索（search，真实 GitHub API）、天气（weather，真实 wttr.in）、待办（todo，有状态）
- **工具注册机制**：每个工具有 name / description / 参数 Schema，LLM 基于 Schema 自主决策
- **Agent 主循环**：用户输入 → LLM 判断「直接回复还是调工具」→ 执行工具 → 结果喂回 → 循环，直到出最终答案
- **Session 隔离**：多个窗口（session_id）互不影响、可随时接续、支持「纯对话追问」和「带工具的追问」
- **Context 管理**：最大轮次限制 + 超长历史的基础压缩
- **状态持久化**：SQLite 落盘（`db.py` 数据访问层），重启不丢记忆
- **前端页面**：浏览器直接对话（聊天气泡、会话切换、加载态、自动滚动）
- **健壮性**：异常处理 + 工具调用 trace 日志
- **测试**：13 个 pytest 用例（含 mock 隔离网络、SQLite 读写）

---

## 核心概念（学习资料）

### 1. 工具注册机制

**问题**：LLM 怎么知道「有哪些工具、每个工具要什么参数」？

**做法**：建一个「工具花名册」，每个工具登记 4 样东西：

```python
TOOLS[name] = {
    "name": name,            # 工具名
    "description": description,   # 干嘛的（给 LLM 看）
    "parameters": parameters,     # 参数说明书 / JSON Schema（给 LLM 看）
    "func": func,                 # 真正干活的函数（给程序用）
}
```

- `description` 和 `parameters`（JSON Schema）是**给 LLM 读的说明书**——它靠这份说明书决定「该不该调这个工具、传什么参数」。说明书写糊了，LLM 就选错工具。
- `func` 是**给程序用的函数本体**。
- 加新工具 = 写个函数 + `register_tool(...)` 登记一次，别的代码一行不用改。

`get_tools()` 负责把扁平的花名册「翻译」成 OpenAI SDK 要的嵌套格式（外面包一层 `{"type": "function", "function": {...}}`）。

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
- 把结果喂回去要用 `role="tool"` 消息，并带上 `tool_call_id`（LLM 靠它知道「这结果回答哪次调用」）。
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
- 工具的「有状态」（todo）也按 session 隔离：用一个 `CURRENT_SESSION` 上下文变量，agent 执行工具前先设置它，工具读它就知道该动哪份待办。
- **LLM 决定业务参数（city/expression/item），harness 决定上下文（session_id）**——后者不该让 LLM 决定。

### 4. Context 管理

- **最大轮次**：`MAX_ROUNDS = 5`，限制工具调用轮数，防死循环。
- **基础压缩**：消息超过 `MAX_MESSAGES` 时，只保留 `system 提示 + 最近 N 条`：

```python
return [messages[0]] + messages[-(MAX_MESSAGES - 1):]
```

- 塞进 context 的：system 提示、用户输入、LLM 的 tool_calls、工具结果、最终答案。
- **不塞**的：`reasoning_content`（思考过程）——它是一次性内部推理，下一轮用不上，塞进去浪费。

### 5. 状态持久化：SQLite 分层

**问题**：内存状态一重启就没了（进程生命周期）。最开始的解法是 JSON 文件，但更专业的做法是用真正的数据库。

**做法**：把「跟数据库打交道」的逻辑单独抽到 `db.py`（**数据访问层**），agent/tools 只写业务，要存要读就调 `db.xxx()`。

- **分层**：以后想换 MySQL / Redis，只改 `db.py`，业务代码一行不动。
- **两张表**：`messages`（消息）+ `todos`（待办），都有 `session_id`（隔离）+ `created_at`（时间戳）。
- **tool_calls 序列化**：工具调用信息是 `list[dict]`，SQLite 存不了 → 存时 `json.dumps` 成字符串，读时 `json.loads` 还原。
- **写透（write-through）**：`_append()` 同时写内存缓存和 SQLite，业务代码不关心磁盘。
- **system 提示不存库**：固定的一句话，每次 `get_session` 时 prepend，不塞冗余数据。
- **参数化查询**：SQL 里用 `?` 占位符传值，**防 SQL 注入**（别用字符串拼接拼 SQL）。

### 6. 测试：mock 隔离外部依赖

测试只该测「你自己的代码」，不该测「别人的服务器今天在不在线」。真实 HTTP 调用有三个问题：**慢、要联网、结果会变（flaky）**。

**做法**：用 pytest 的 `monkeypatch` 把 `requests.get` 换成「替身」（fake），返回写死的数据：

```python
def test_weather(monkeypatch):
    class Faker:
        def raise_for_status(self): pass
        text = "北京: ✨ +20°C"
    monkeypatch.setattr(tools.requests, "get", lambda *a, **k: Faker())
    assert "北京" in tools.weather("北京")
```

- 替身只要提供代码用到的成员：`.raise_for_status()`、`.text`、`.json()`。
- 数据库测试用 `autouse` fixture 把 `DB_FILE` 换成临时文件，每个测试独立，**绝不污染真实 agent.db**。

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

浏览器打开 **http://127.0.0.1:8000** —— 直接在弹出的聊天页面里对话（比在 `/docs` 里填 JSON 舒服多了）。左上角可切换会话 ID（不同 ID = 不同记忆）。

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
| `db.py` | 数据访问层：SQLite 读写（messages / todos）|
| `server.py` | FastAPI 接口 + 首页 |
| `index.html` | 前端聊天页面（HTML + CSS + JS，单文件无框架）|
| `test_agents.py` | 13 个 pytest 测试用例 |
| `requirements.txt` | 依赖清单 |
| `.env` | 密钥（不入 git）|

---


## 技术栈

- Python 3.11 / FastAPI / uvicorn
- openai SDK（直连 DeepSeek）
- sqlite3（Python 标准库，免安装）
- requests（调真实 API）
- simpleeval（安全数学表达式求值）
- pytest（测试，含 monkeypatch / fixture）
