import json
import sys
from pathlib import Path

# 这里表示到上一层的目录
ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from app.services.function_calling_demo import TOOL_SCHEMAS, run_mini_agent  # noqa: E402


QUESTIONS = [
    "计算 (310 - 260) / 260 * 100",
    "退款表的字段有哪些？",
    "4月服装类商品退款率是多少？",
]


def main() -> int:
    print("工具 schema：")
    # 把python对象转换成json字符串，ensure_ascii=False表示不转义非ascii字符，indent=2表示格式化输出，缩进2个空格
    print(json.dumps(TOOL_SCHEMAS, ensure_ascii=False, indent=2))
    print("\n调用案例：")
    for question in QUESTIONS:
        result = run_mini_agent(question)
        print(json.dumps({
            "question": result.question,
            "tool_call": {
                "name": result.tool_call.name,
                "arguments": result.tool_call.arguments,
            },
            "observation": result.observation,
            "final_answer": result.final_answer,
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
