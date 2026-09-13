"""Unit tests must never consume credentials from the owner's .env file."""
import os
from pathlib import Path

import pytest

test_temp = Path(__file__).resolve().parents[1] / "data" / "pytest-temp"
test_temp.mkdir(parents=True, exist_ok=True)
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(test_temp)


@pytest.fixture(autouse=True)
def isolate_model_credentials(monkeypatch):
    for name in ("LLM_API_KEY", "OPENAI_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.setenv(name, "")
