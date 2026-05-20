import ast
import operator
import re
from dataclasses import dataclass
from typing import Any, Callable

from app.services.sql_tools import execute_readonly_sql, get_table_schema


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {   
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "执行安全的四则运算，只支持数字、括号、加减乘除和幂运算。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "需要计算的表达式，例如 '(310 - 260) / 260 * 100'。",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_schema",
            "description": "查询售后分析数据库中某张表的字段结构。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": ["products", "orders", "refunds", "reviews", "tickets"],
                        "description": "要查询结构的表名。",
                    }
                },
                "required": ["table"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_mock_data",
            "description": "执行只读 SQL，查询模拟电商售后数据库。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "只允许 SELECT 语句，不允许写入、删除或修改数据。",
                    }
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class MiniAgentResult:
    question: str
    tool_call: ToolCall | None
    observation: dict[str, Any] | None
    final_answer: str
    llm_raw_response: dict[str, Any] | None = None


def calculator(expression: str) -> dict[str, Any]:
    result = _safe_eval(expression)
    return {"expression": expression, "result": result}


def table_schema_tool(table: str) -> dict[str, Any]:
    return {"table": table, "schema": get_table_schema(table)}


def query_mock_data(sql: str) -> dict[str, Any]:
    result = execute_readonly_sql(sql)
    return result.model_dump()

# Callable 专门用来表示这是一个函数，然后这里...表示的是参数，接收任意类型的参数，返回值是一个 dict[str, Any] 的字典
TOOL_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "calculator": calculator,
    "get_table_schema": table_schema_tool,
    "query_mock_data": query_mock_data,
}


def run_mini_agent(question: str) -> MiniAgentResult:
    import json
    import httpx
    from app.core.config import settings
    
    # 1. 组装给大模型的历史消息
    messages = [{"role": "user", "content": question}]
    
    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    
    # 第一次向大模型发起请求：带上 tools 告诉它我们有哪些函数可用
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "tools": TOOL_SCHEMAS,
        "tool_choice": "auto"
    }
    
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    
    # 发送 HTTP 请求调用 DeepSeek / 大模型
    with httpx.Client() as client:
        resp = client.post(url, headers=headers, json=payload, timeout=60.0)
        resp.raise_for_status()
        llm_response = resp.json()
        
    print("大模型原始返回内容（供调试参考）：")
    print(json.dumps(llm_response, ensure_ascii=False, indent=2))
    message = llm_response["choices"][0]["message"]
    
    # 2. 判断大模型是否决定调用工具
    if not message.get("tool_calls"):
        # 大模型认为不需要调用工具，直接给出了文本回答
        return MiniAgentResult(
            question=question,
            tool_call=None,
            observation=None,
            final_answer=message.get("content", ""),
            llm_raw_response=llm_response
        )
        
    # 3. 大模型决定调用工具，解析返回的 JSON 拿到工具名和参数
    tool_call_data = message["tool_calls"][0]
    func_name = tool_call_data["function"]["name"]
    func_args = json.loads(tool_call_data["function"]["arguments"])
    
    tool_call = ToolCall(name=func_name, arguments=func_args)
    
    # 4. 执行本地对应的 Python 工具函数
    tool = TOOL_REGISTRY.get(tool_call.name)
    if not tool:
        observation = {"error": f"找不到对应的工具：{tool_call.name}"}
    else:
        try:
            observation = tool(**tool_call.arguments)
        except Exception as e:
            observation = {"error": str(e)}
            
    # 5. 第二次调用大模型：将函数的执行结果发回给它，让它总结出一段人话
    # 先把大模型的历史决策 message 塞进去
    messages.append(message)
    # 再把函数真实执行结果作为 role="tool" 的角色塞进去
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call_data["id"],
        "name": func_name,
        "content": json.dumps(observation, ensure_ascii=False)
    })
    
    payload_second = {
        "model": settings.llm_model,
        "messages": messages
    }
    
    with httpx.Client() as client:
        resp2 = client.post(url, headers=headers, json=payload_second, timeout=60.0)
        resp2.raise_for_status()
        second_response = resp2.json()
        
    final_answer = second_response["choices"][0]["message"].get("content", "")
    
    return MiniAgentResult(
        question=question,
        tool_call=tool_call,
        observation=observation,
        final_answer=final_answer,
        llm_raw_response=llm_response  # 返回第一次调用产生的原始内容，供你调试查看
    )


def _safe_eval(expression: str) -> float:
    allowed_binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
    }
    allowed_unary_ops = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binary_ops:
            return allowed_binary_ops[type(node.op)](eval_node(node.left), eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary_ops:
            return allowed_unary_ops[type(node.op)](eval_node(node.operand))
        raise ValueError("Unsupported expression.")

    tree = ast.parse(expression, mode="eval")
    return round(eval_node(tree), 6)
