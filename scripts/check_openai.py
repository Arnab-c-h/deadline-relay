"""Make three real OpenAI interpretation calls; never write to connected apps."""
import json
from pathlib import Path

from dotenv import load_dotenv

from relay.intent import ModelError, OpenAIInterpreter

ROOT = Path(__file__).resolve().parents[1]


def main():
    load_dotenv(ROOT / ".env", override=False)
    model = OpenAIInterpreter.from_env()
    checks = []
    cases = [
        ("Move the release deadline to September 24, 2026.", "date", "2026-09-24"),
        ("Move the release deadline to next Friday.", "clarification", None),
        ("Move the release deadline to September 24, 2026 and email the whole team.", "unsupported", None),
    ]
    for request, status, target in cases:
        try:
            result = model.interpret(request, "Asia/Kolkata")
        except ModelError as error:
            print(str(error))
            return 1
        passed = result["status"] == status and result["requested_date"] == target
        checks.append({"request": request, "passed": passed, "result": result})
        print(f"{'PASS' if passed else 'FAIL'}: {status}; model={result['evidence']['model']}; "
              f"latency_ms={result['evidence']['latency_ms']}", flush=True)
    target = ROOT / "data" / "openai-smoke.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(checks, indent=2), encoding="utf-8")
    print("Evidence saved to data/openai-smoke.json. No connected-app writes performed.")
    return 0 if all(check["passed"] for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
