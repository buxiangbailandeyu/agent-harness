# test_agent.py —— 测试 agent 的各个零件
import tools
import agent


def test_calculator():
    assert tools.calculator("1+2*3") == "1+2*3=7"

def test_calculator_no_crash():
    # 非法表达式也不该让程序崩，应返回错误信息
    result = tools.calculator("1/0")
    assert "错误" in result

def test_search():
    assert "AI" in tools.search("AI")

def test_weather():
    assert "北京" in tools.weather("北京")

def test_four_tools_registered():
    assert len(tools.TOOLS) == 4
    assert set(tools.TOOLS.keys()) == {"calculator", "search", "weather", "todo"}

def test_get_tools_format():
    result = tools.get_tools()
    assert len(result) == 4
    for t in result:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "parameters" in t["function"]

def test_sessions_independent():
    a = agent.get_session("w1")
    b = agent.get_session("w2")
    assert a is not b

def test_same_session_reused():
    a1 = agent.get_session("w1")
    a2 = agent.get_session("w1")
    assert a1 is a2

def test_todo_isolated():
    tools.TODOS = {}          # 重置，保证测试之间互不影响
    tools.CURRENT_SESSION = "w1"
    tools.todo("add", "买牛奶")
    tools.CURRENT_SESSION = "w2"
    assert "暂无待办" in tools.todo("list")

def test_trim_short_unchanged():
    msgs = [{"role": "system", "content": "s"}]
    assert agent.trim_messages(msgs) == msgs

def test_trim_caps_long_history():
    msgs = [{"role": "system", "content": "s"}]
    for i in range(30):
        msgs.append({"role": "user", "content": str(i)})
    result = agent.trim_messages(msgs)
    assert result[0]["role"] == "system"
    assert len(result) <= agent.MAX_MESSAGES