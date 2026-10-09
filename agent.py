import os
import json
from openai import OpenAI
from dotenv import load_dotenv

from tools import get_tools, TOOLS
import tools
import db

load_dotenv()  # 加载 .env 文件中的环境变量

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

db.init_db()   # 启动时建表（幂等，表已存在就跳过）

SESSIONS = {}   # session_id -> {"messages": [...]}，内存缓存，每个 session 独立一份历史

MAX_ROUNDS = 5
MAX_MESSAGES = 20  # 每个 session 最多保留的消息数，超过就丢掉最早的

SYSTEM_PROMPT = "你是一个会使用工具的助手。"


def trim_messages(messages):
    """裁剪消息列表，保留最新的 MAX_MESSAGES 条"""
    if len(messages) <= MAX_MESSAGES:
        return messages
    return [messages[0]] + messages[-(MAX_MESSAGES - 1):]


def msg_to_dict(msg):
    """把 OpenAI 返回的 message 对象转成普通 dict（才能存 SQLite）"""
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = []
        for c in msg.tool_calls:
            d["tool_calls"].append({
                "id": c.id,
                "type": "function",
                "function": {
                    "name": c.function.name,
                    "arguments": c.function.arguments,
                },
            })
    return d


def _append(session, session_id, msg):
    """同时写进内存缓存和 SQLite，保证两边一致"""
    session["messages"].append(msg)
    db.append_message(session_id, msg)


def get_session(session_id):
    """取某个 session；不存在就从 SQLite 读历史重建，读不到就新建"""
    if session_id not in SESSIONS:
        history = db.load_messages(session_id)
        SESSIONS[session_id] = {
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + history,
        }
    return SESSIONS[session_id]


def ask(user_text, session_id="default"):
    """按 session 隔离的 agent 循环：每个窗口各记各的历史"""
    session = get_session(session_id)
    _append(session, session_id, {"role": "user", "content": user_text})

    for _ in range(MAX_ROUNDS):
        try:
            response = client.chat.completions.create(
                model="deepseek-flash",
                messages=trim_messages(session["messages"]),
                tools=get_tools(),
            )
        except Exception as e:
            return f"（调用 LLM 出错: {e}）"

        msg = response.choices[0].message

        if msg.tool_calls:
            _append(session, session_id, msg_to_dict(msg))
            tools.CURRENT_SESSION = session_id
            for call in msg.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments)
                    print(f"[TRACE] 调用工具 {name}，参数: {args}")
                    func = TOOLS[name]["func"]
                    result = func(**args)
                except Exception as e:
                    result = f"工具执行出错: {e}"   # 出错不崩，把错误当结果
                print(f"[TRACE] {name} 返回: {result}")
                _append(session, session_id, {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                })
        else:
            _append(session, session_id, msg_to_dict(msg))
            return msg.content

    return "（达到最大轮次限制，工具可能陷入了循环）"


def ask_stream(user_text, session_id="default"):
    """流式版 ask：LLM 边生成边把 token yield 出去（供 SSE 用）。

    工具调用轮不吐字（content 为空），最终答案那一轮才逐字吐。
    """
    session = get_session(session_id)
    _append(session, session_id, {"role": "user", "content": user_text})

    for _ in range(MAX_ROUNDS):
        try:
            stream = client.chat.completions.create(
                model="deepseek-flash",
                messages=trim_messages(session["messages"]),
                tools=get_tools(),
                stream=True,
            )
        except Exception as e:
            yield f"（调用 LLM 出错: {e}）"
            return

        content_parts = []
        tool_calls = {}   # index -> {"id":..., "name":..., "arguments":...}

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content_parts.append(delta.content)
                yield delta.content                     # 关键：实时把 token 吐给前端
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    t = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        t["id"] = tc.id
                    if tc.function and tc.function.name:
                        t["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        t["arguments"] += tc.function.arguments   # 参数是分片到的，要拼起来

        if tool_calls:
            # 这轮要调工具：把 assistant 消息 + 各工具结果喂回，继续循环
            _append(session, session_id, {
                "role": "assistant",
                "content": "".join(content_parts) or "",
                "tool_calls": [
                    {"id": t["id"], "type": "function",
                     "function": {"name": t["name"], "arguments": t["arguments"]}}
                    for t in tool_calls.values()
                ],
            })
            tools.CURRENT_SESSION = session_id
            for t in tool_calls.values():
                name = t["name"]
                try:
                    args = json.loads(t["arguments"])
                    print(f"[TRACE] 调用工具 {name}，参数: {args}")
                    func = TOOLS[name]["func"]
                    result = func(**args)
                except Exception as e:
                    result = f"工具执行出错: {e}"
                print(f"[TRACE] {name} 返回: {result}")
                _append(session, session_id, {
                    "role": "tool",
                    "tool_call_id": t["id"],
                    "content": result,
                })
        else:
            # 最终答案：token 已经在上面 yield 过了，这里落库即可
            _append(session, session_id, {"role": "assistant", "content": "".join(content_parts)})
            return

    yield "（达到最大轮次限制，工具可能陷入了循环）"


if __name__ == "__main__":
    answer = ask("计算 1+2*3")
    print("最终答案:", answer)
