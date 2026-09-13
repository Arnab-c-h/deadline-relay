import json

import httpx
import pytest

from relay import intent


def response(content=None, **overrides):
    return {"id": "resp_test", "model": "gpt-5-mini", "status": "completed",
            "usage": {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100},
            "output": [{"type": "message", "content": content or [{"type": "output_text", "text": json.dumps(
                {"status": "date", "requested_date": "2026-09-24", "message": "Move release to September 24."})}]}],
            **overrides}


def interpreter(handler):
    assert hasattr(intent, "OpenAIInterpreter"), "Real OpenAI interpreter is not implemented"
    return intent.OpenAIInterpreter("test-key", "gpt-5-mini", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_real_interpreter_uses_strict_schema_and_records_actual_usage():
    def handler(request):
        body = json.loads(request.content)
        assert request.url == "https://api.openai.com/v1/responses"
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert "tools" not in body
        return httpx.Response(200, json=response(), headers={"x-request-id": "req_test"})
    result = interpreter(handler).interpret("Move release to September 24, 2026", "Asia/Kolkata")
    assert result["requested_date"] == "2026-09-24"
    assert result["evidence"]["usage"]["total_tokens"] == 100
    assert result["evidence"]["request_id"] == "req_test"
    assert result["evidence"]["latency_ms"] >= 0


@pytest.mark.parametrize("payload", [
    response(status="incomplete"),
    response(content=[{"type": "refusal", "refusal": "No"}]),
    response(content=[{"type": "output_text", "text": "not json"}]),
    response(content=[{"type": "output_text", "text": json.dumps(
        {"status": "date", "requested_date": "2026-02-30", "message": "Invalid"})}]),
    response(content=[{"type": "output_text", "text": json.dumps(
        {"status": "unsupported", "requested_date": "2026-09-24", "message": "Mixed output"})}]),
    response(content=[{"type": "output_text", "text": json.dumps(
        {"status": "date", "requested_date": "2026-09-24", "message": "x", "operations": []})}]),
])
def test_refusal_incomplete_and_invalid_output_never_fall_back_to_date_parser(payload):
    model = interpreter(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(intent.ModelError):
        model.interpret("Move to September 24, 2026", "Asia/Kolkata")


@pytest.mark.parametrize("code", [401, 403, 404, 429, 500])
def test_api_errors_do_not_expose_response_body_or_credentials(code):
    model = interpreter(lambda request: httpx.Response(code, text="test-key private provider details"))
    with pytest.raises(intent.ModelError) as caught:
        model.interpret("Move to September 24, 2026", "Asia/Kolkata")
    assert "test-key" not in str(caught.value)
    assert "private" not in str(caught.value)


def test_health_verifies_model_access_and_missing_credentials_make_no_request():
    model = interpreter(lambda request: httpx.Response(200, json={"id": "gpt-5-mini"}))
    assert model.health()["status"] == "ready"
    model.api_key = ""
    assert model.health()["status"] == "missing"


def test_live_service_uses_model_evidence_and_keeps_alternative_bound_to_parent(tmp_path):
    from relay.fixtures import build_fixture
    from relay.service import RelayService, WorkflowError, plan_hash
    from relay.store import Store

    model = interpreter(lambda request: httpx.Response(200, json=response(content=[{
        "type": "output_text", "text": json.dumps({"status": "date", "requested_date": "2026-09-18",
                                                    "message": "Move to September 18."})}])))
    store = Store(tmp_path / "test.sqlite")
    snapshot = build_fixture()
    snapshot["mode"] = "live"
    store.save("snapshots", snapshot["id"], snapshot)
    service = RelayService(store, object(), mode="live", interpreter=model)
    plan = service.plan(snapshot["id"], "Move to September 18, 2026")
    assert plan["status"] == "infeasible" and plan["operations"] == []
    assert plan["interpretation"]["response_id"] == "resp_test"
    assert plan_hash(plan) == plan["hash"]
    alternative = service.plan(snapshot["id"], plan["request"], plan["proposed_date"], plan["id"])
    assert alternative["status"] == "ready" and len(alternative["operations"]) == 5
    assert alternative["interpretation"]["method"] == "approved-alternative"
    with pytest.raises(WorkflowError):
        service.plan(snapshot["id"], plan["request"], "2026-09-23", plan["id"])
