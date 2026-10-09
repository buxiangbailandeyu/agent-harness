import requests
from simpleeval import simple_eval

def calculator(expression:str)->str:
    """计算一个数学表达式，返回结果"""
    try:
        result=simple_eval(expression)
        return f"{expression}={result}"
    except Exception as e:
        return f"计算错误: {e}"

def search(query: str) -> str:
    """搜索Github项目,返回相关项目"""
    try:
        r=requests.get(
            "https://api.github.com/search/repositories",
            params={"q":query,"per_page":3},
            headers={"User-Agent":"agent-demo"},
            timeout=5,
        )
        r.raise_for_status()
        data=r.json()
        items=data["items"]
        if not items:
            return f"未找到{query}相关的项目"
        result="搜索结果:\n"
        for item in items:
            result += f"{item['full_name']},{item['html_url']},{item['description']or'(无简介)'},{item['stargazers_count']}\n"
        return result
    except Exception as e:
        return f"搜索失败: {e}"
    

def weather(city: str) -> str:
    """查询某城市天气（真实 API：wttr.in）"""
    try:
        url = f"https://wttr.in/{city}?format=3&lang=zh"
        r = requests.get(url, timeout=5)
        r.raise_for_status()       # 状态码不是 200 就抛异常
        return r.text.strip()      # 去掉首尾的换行/空格
    except Exception as e:
        return f"查询天气失败: {e}"

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
    description="搜索 GitHub 上的项目，返回与 query 相关的结果。",
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