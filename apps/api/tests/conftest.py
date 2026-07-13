import sys
from pathlib import Path

import pytest

# Ensure the API app directory is in sys.path
api_dir = Path(__file__).resolve().parents[1]
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))


@pytest.fixture(autouse=True)
def disable_external_llm_calls(monkeypatch):
    """Keep unit tests deterministic and prevent accidental paid/network calls."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "siliconflow_api_key", "")
