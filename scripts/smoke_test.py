import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps" / "api"
PYTHON = API_DIR / ".venv" / "Scripts" / "python.exe"
PORT = int(os.environ.get("SMOKE_PORT", "8010"))
BASE_URL = f"http://127.0.0.1:{PORT}"


def post_chat(message: str) -> dict:
    payload = json.dumps({"message": message, "session_id": "smoke"}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    if not PYTHON.exists():
        print(f"Missing venv python: {PYTHON}")
        return 1

    process = subprocess.Popen(
        [str(PYTHON), "-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=API_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(3)
        health = urllib.request.urlopen(f"{BASE_URL}/health", timeout=10)
        assert health.status == 200
        cases = [
            ("4月服装类商品退款率是多少？", "sql"),
            ("退款率指标口径是什么？", "rag"),
            ("4月服装类商品退款率为什么升高？请结合数据和退款政策给出分析。", "hybrid"),
        ]
        for message, expected_route in cases:
            response = post_chat(message)
            assert response["route"] == expected_route, response
            assert response["answer"], response
        print("smoke test passed")
        return 0
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
