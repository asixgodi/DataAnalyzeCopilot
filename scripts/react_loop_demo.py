import json
import sys
from dataclasses import asdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
sys.path.insert(0, str(API_DIR))

from app.services.react_loop import run_react_agent  # noqa: E402


CASES = [
    "4月服装类商品退款率是多少？",
    "4月服装类商品退款率是多少？请先生成错误SQL再修复",
    "计算 100 / 0",
    "请一直重试，演示死循环控制",
]


def main() -> int:
    for question in CASES:
        result = run_react_agent(question)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        print("-" * 80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
