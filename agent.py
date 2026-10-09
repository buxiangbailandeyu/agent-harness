import os
from openai import OpenAI
from dotenv import load_dotenv
import json
from tools import get_tools,TOOLS
import tools
load_dotenv()  # 加载 .env 文件中的环境变量

client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

SESSIONS = {}   # session_id -> {"messages": [...]}，每个 session 独立一份历史
SAVE_FILE = "sessions.json"
MAX_ROUNDS = 5

MAX_MESSAGES = 20  # 每个 session 最多保留的消息数，超过就丢掉最早的

def trim_messages(messages):
    """裁剪消息列表，保留最新的 MAX_MESSAGES 条"""
    if len(messages) <= MAX_MESSAGES:
        return messages
    return [messages[0]]+messages[-(MAX_MESSAGES-1):]  # 保留最新的 MAX_MESSAGES 条]

def msg_to_dict(msg):
    """把 OpenAI 返回的 message 对象转成普通 dict（才能存 JSON）"""
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

def save_sessions():
    """把 SESSIONS 和 TODOS 存到磁盘"""
    with open(SAVE_FILE, "w", encoding="utf-8") as f:
        json.dump({"sessions": SESSIONS, "todos": tools.TODOS}, f, ensure_ascii=False)

def load_sessions():
    """启动时从磁盘读回 SESSIONS 和 TODOS（文件不存在就跳过）"""
    if not os.path.exists(SAVE_FILE):
        return
    with open(SAVE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    SESSIONS.clear()
    SESSIONS.update(data.get("sessions", {}))
    tools.TODOS.clear()
    tools.TODOS.update(data.get("todos", {}))

def get_session(session_id):
    """取某个 session;不存在就新建一个"""
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {
            "messages": [
                {"role": "system", "content": "你是一个会使用工具的助手。"},
            ],
        }
    return SESSIONS[session_id]

def ask(user_text, session_id="default"):
    """按 session 隔离的 agent 循环：每个窗口各记各的历史"""
    session = get_session(session_id)
    session["messages"].append({"role": "user", "content": user_text})

    for _ in range(MAX_ROUNDS):
        try:
            response = client.chat.completions.create(
                model="deepseek-flash",
                messages=trim_messages(session["messages"]),
                tools=get_tools(),e
            )
        except Exception as e:
            save_sessions()  # 出错时也保存一下，避免丢掉历史
            return f"（调用 LLM 出错: {e}）"

        msg = response.choices[0].message

        if msg.tool_calls:
            session["messages"].append(msg_to_dict(msg))
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

                session["messages"].append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                })

        else:
            session["messages"].append(msg_to_dict(msg))
            save_sessions()  # 每轮都保存一下，避免丢掉历史
            return msg.content
    save_sessions()  # 超过 MAX_ROUNDS 也保存一下
    return "（达到最大轮次限制，工具可能陷入了循环）"

load_sessions()

if __name__=="__main__":
    answer = ask("计算 1+2*3")
    print("最终答案:", answer)