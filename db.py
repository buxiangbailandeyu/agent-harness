"""数据访问层：所有跟 SQLite 打交道的事都集中在这里。

agent.py / tools.py 只负责业务，要存要读就调这里。
以后想换 MySQL / Redis，只改这个文件即可。
"""
import sqlite3
import json

DB_FILE = "agent.db"   # 数据库文件名（测试里会被 monkeypatch 成临时文件）


def get_conn():
    """开一个数据库连接"""
    return sqlite3.connect(DB_FILE)


def init_db():
    """建表（IF NOT EXISTS = 表已存在就跳过，所以可以放心反复调用）"""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            tool_call_id TEXT,
            tool_calls TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            item TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    conn.commit()
    conn.close()


def append_message(session_id, msg):
    """存一条消息。msg 是 dict，可能含 role / content / tool_call_id / tool_calls"""
    # tool_calls 是个 list[dict]，SQLite 存不了，先序列化成 JSON 字符串
    tool_calls_json = json.dumps(msg["tool_calls"], ensure_ascii=False) if msg.get("tool_calls") else None
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages (session_id, role, content, tool_call_id, tool_calls) VALUES (?, ?, ?, ?, ?)",
        (session_id, msg.get("role"), msg.get("content"), msg.get("tool_call_id"), tool_calls_json),
    )
    conn.commit()
    conn.close()


def load_messages(session_id):
    """读出一个会话的所有消息，按插入顺序返回（不含 system，system 由 agent 自己加）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content, tool_call_id, tool_calls FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()

    messages = []
    for role, content, tool_call_id, tool_calls in rows:
        m = {"role": role, "content": content}
        if tool_call_id:
            m["tool_call_id"] = tool_call_id
        if tool_calls:
            m["tool_calls"] = json.loads(tool_calls)   # 把 JSON 字符串还原回 list[dict]
        messages.append(m)
    return messages


def add_todo(session_id, item):
    conn = get_conn()
    conn.execute("INSERT INTO todos (session_id, item) VALUES (?, ?)", (session_id, item))
    conn.commit()
    conn.close()


def list_todos(session_id):
    conn = get_conn()
    rows = conn.execute("SELECT item FROM todos WHERE session_id = ? ORDER BY id", (session_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def remove_todo(session_id, item):
    conn = get_conn()
    conn.execute("DELETE FROM todos WHERE session_id = ? AND item = ?", (session_id, item))
    conn.commit()
    conn.close()
