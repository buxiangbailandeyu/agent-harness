from simpleeval import simple_eval

def calculator(expression:str)->str:
    """计算一个数学表达式，返回结果"""
    try:
        result=simple_eval(expression)
        return f"{expression}={result}"
    except Exception as e:
        return f"计算错误: {e}"

def search(query: str) -> str:
    """搜索网络，返回结果（模拟）"""
    return f"（模拟搜索结果）关于「{query}」：这是假数据，真实的搜索以后接搜索引擎 API。"

def weather(city: str) -> str:
    """查询某城市天气（模拟）"""
    return f"（模拟天气）{city} 今天晴，25°C，微风。"

TODOS = {}   # session_id -> [todo1, todo2, ...]，每个 session 独立一份待办列表
CURRENT_SESSION = None 


def todo(action: str, item: str = "") -> str:
    """管理待办事项。action 是 add / list / remove"""
    todos = TODOS.setdefault(CURRENT_SESSION, [])   # 当前 session 的待办列表

    if action == "add":
        todos.append(item)
        return f"已添加待办: {item}"

    elif action == "list":
        if not todos:
            return "暂无待办"
        result = "待办列表:"
        for t in todos:
            result += f"\n- {t}"
        return result

    elif action == "remove":
        if item in todos:
            todos.remove(item)
            return f"已删除待办: {item}"
        return f"待办 {item} 不存在"

    else:
        return f"未知操作: {action}"


TOOLS={}


def register_tool(name,description,parameters,func):
    """注册一个工具"""
    TOOLS[name]={
        "name":name,  #工具名称
        "description":description,  #工具描述 （给 LLM 看）
        "parameters":parameters,    #参数说明书
        "func":func #真正干活的函数（给程序用）
    }

def get_tools():
    """把花名册转成openai认识的 tools 格式"""
    tools=[] #空列表，装翻译后的结果
    for t in TOOLS.values():   
       tools.append({
           "type":"function",
           "function":{
               "name":t["name"],
               "description":t["description"],
                "parameters":t["parameters"]
           },
       })
    return tools

register_tool(
    name="calculator",
    description="计算一个数学表达式，返回结果",
    parameters={
        "type":"object",
        "properties":{
            "expression":{
                "type":"string",
                "description":"数学表达式"
            },
        },
        "required":["expression"],
    },
    func=calculator,
)   

register_tool(
    name="search",
    description="搜索网络，返回与 query 相关的结果。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要搜索的内容",
            },
        },
        "required": ["query"],
    },
    func=search,
)

register_tool(
    name="weather",
    description="查询某城市的天气。",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "城市名，例如「北京」",
            },
        },
        "required": ["city"],
    },
    func=weather,
)

register_tool(
    name="todo",
    description="管理待办事项：添加(add)、列出(list)或删除(remove)待办。",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：add / list / remove",
            },
            "item": {
                "type": "string",
                "description": "待办内容（add 或 remove 时需要，list 不需要）",
            },
        },
        "required": ["action"],   # 只有 action 必填，item 可空
    },
    func=todo,
)