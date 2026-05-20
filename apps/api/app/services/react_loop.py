import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.function_calling_demo import calculator
from app.services.sql_tools import execute_readonly_sql, get_table_schema


StepStatus = Literal["success", "error", "stopped"]


@dataclass
class ReactStep:
    iteration: int
    thought: str
    action: str | None
    action_input: dict[str, Any] | None
    observation: dict[str, Any]
    status: StepStatus


@dataclass
class ReactResult:
    question: str
    final_answer: str
    stopped_reason: str
    steps: list[ReactStep] = field(default_factory=list)


def run_react_agent(question: str, max_iterations: int = 4) -> ReactResult:
    import json
    import httpx
    from app.core.config import settings
    from app.services.function_calling_demo import TOOL_SCHEMAS, TOOL_REGISTRY

    steps: list[ReactStep] = []
    
    # 初始化对话上下文
    messages = [
        {
            "role": "system", 
            "content": "你是一个严谨的数据分析助手。在回答用户的数据查询要求前，请务必先调用 get_table_schema 工具查看数据库表结构，确认表和字段的准确名称后，再生成最终的数据查询 SQL。如果你认为已经获取了足够的数据来解答用户，请直接输出最终中文回答。"
        },
        {"role": "user", "content": question}
    ]

    headers = {
        "Authorization": f"Bearer {settings.siliconflow_api_key}",
        "Content-Type": "application/json",
    }
    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"

    # 开启大模型的推演循环核心！这就是 ReAct 的 "循环" 体现
    for iteration in range(1, max_iterations + 1):
        payload = {
            "model": settings.llm_model,
            "messages": messages,
            "tools": TOOL_SCHEMAS,
            "tool_choice": "auto"
        }

        # 1. 向大模型发起推演请求
        with httpx.Client() as client:
            resp = client.post(url, headers=headers, json=payload, timeout=60.0)
            resp.raise_for_status()
            llm_response = resp.json()

        message = llm_response["choices"][0]["message"]
        
        # 将大模型当前的思考与决策追加进上下文记忆中
        messages.append(message)
        
        # DeepSeek 等模型有时会在 content 里输出它的思考过程（Thought）
        thought = message.get("content") or f"准备执行第 {iteration} 轮工具调用..."

        # 2. 判断大模型是否决定终止调用给出最终答案
        if not message.get("tool_calls"):
            # 如果没有工具调用请求了，说明大模型认为它的信息找够了，直接回答
            steps.append(
                ReactStep(
                    iteration=iteration,
                    thought=thought,
                    action="finish",
                    action_input=None,
                    observation={"answer": thought},
                    status="success",
                )
            )
            return ReactResult(
                question=question, 
                final_answer=thought, 
                stopped_reason="finished", 
                steps=steps
            )

        # 3. 大模型决定调用工具，我们解析并遍历执行
        tool_calls = message["tool_calls"]
        for tool_call in tool_calls:
            func_name = tool_call["function"]["name"]
            func_args_str = tool_call["function"]["arguments"]
            try:
                func_args = json.loads(func_args_str)
            except json.JSONDecodeError:
                func_args = {}

            # 本地执行真实工具
            tool = TOOL_REGISTRY.get(func_name)
            if not tool:
                observation = {"ok": False, "error": f"找不到工具 {func_name}"}
            else:
                try:
                    res = tool(**func_args)
                    observation = {"ok": True, "data": res}
                except Exception as e:
                    observation = {"ok": False, "error": str(e)}

            # 4. 把工具执行的观测结果，封装成 "tool" 角色发还给大模型
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": func_name,
                "content": json.dumps(observation, ensure_ascii=False)
            })

            # 记录在 Agent 的履历步骤中，供展示给前端界面
            steps.append(
                ReactStep(
                    iteration=iteration,
                    thought=thought,
                    action=func_name,
                    action_input=func_args,
                    observation=observation,
                    status="success" if observation["ok"] else "error",
                )
            )

        # 这里循环结束，马上进入下一次循环：带着刚刚追加了工具执行结果的 messages 再次去请求 LLM！

    return ReactResult(
        question=question,
        final_answer="此请求太复杂，达到最大推理次数仍然未完成，被保护机制终止循环。",
        stopped_reason="max_iterations",
        steps=steps,
    )
