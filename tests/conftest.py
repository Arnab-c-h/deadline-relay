"""Keep pytest temporary files in the ignored project data directory on Windows."""
import os
from pathlib import Path

test_temp = Path(__file__).resolve().parents[1] / "data" / "pytest-temp"
test_temp.mkdir(parents=True, exist_ok=True)
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(test_temp)
