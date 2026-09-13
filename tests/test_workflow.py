from copy import deepcopy

import pytest

from relay.providers.base import ProviderError
from relay.service import RelayService, WorkflowError
from relay.simulation import SimulationProvider
from relay.store import Store


@pytest.fixture
def system(tmp_path):
    store = Store(tmp_path / "test.sqlite")
    provider = SimulationProvider(store)
    service = RelayService(store, provider, mode="simulated")
    return service, provider, store


def ready(service):
    snapshot = service.snapshot()
    return service.plan(snapshot["id"], "Move delivery to September 24, 2026")


def approve(service, plan, key="approval-1"):
    return service.approve(plan["id"], 1, plan["hash"], key)["run_id"]


def test_planning_never_writes_and_alternative_needs_separate_approval(system):
    service, provider, _ = system
    original = deepcopy(provider.snapshot()["records"])
    snapshot = service.snapshot()
    blocked = service.plan(snapshot["id"], "Move release to September 18, 2026")
    assert blocked["status"] == "infeasible"
    assert blocked["operations"] == []
    with pytest.raises(WorkflowError):
        approve(service, blocked)
    alternative = service.plan(snapshot["id"], blocked["request"], "2026-09-24", blocked["id"])
    assert alternative["status"] == "ready"
    assert provider.snapshot()["records"] == original


def test_approved_run_verifies_five_changes_and_preserves_other_records(system):
    service, provider, _ = system
    before = deepcopy(provider.snapshot()["records"])
    plan = ready(service)
    run_id = approve(service, plan)
    service.execute(run_id)
    run = service.run(run_id)
    assert run["status"] == "VERIFIED", run
    assert len(run["operations"]) == 5
    assert all(op["status"] == "VERIFIED" for op in run["operations"])
    records = provider.snapshot()["records"]
    assert records["calendar:M2"]["fields"]["start"] == "2026-09-24T15:00:00+05:30"
    assert records["notion:T4"]["fields"]["Schedule"]["start"] == "2026-09-22"
    assert records["github:REL"]["fields"]["due_on"] == "2026-09-24T12:30:00Z"
    for key in ("notion:T1", "notion:T2", "calendar:M1", "notion:U1", "calendar:U2"):
        assert records[key] == before[key]
    assert records["calendar:M2"]["fields"]["description"] == before["calendar:M2"]["fields"]["description"]


def test_hash_and_version_tampering_cannot_approve(system):
    service, _, _ = system
    plan = ready(service)
    with pytest.raises(WorkflowError):
        service.approve(plan["id"], 1, "fake", "tamper")
    with pytest.raises(WorkflowError):
        service.approve(plan["id"], 2, plan["hash"], "tamper-version")


def test_duplicate_approval_and_repeated_resume_do_not_repeat_mutations(system):
    service, provider, _ = system
    plan = ready(service)
    run_id = approve(service, plan)
    assert approve(service, plan) == run_id
    assert approve(service, plan, "different-key") == run_id
    service.execute(run_id)
    before = deepcopy(provider.snapshot()["records"])
    service.resume(run_id, "resume-1")
    service.execute(run_id)
    assert provider.snapshot()["records"] == before
    assert all(op["attempts"] == 1 for op in service.run(run_id)["operations"])


def test_reusing_idempotency_key_for_other_plan_conflicts(system):
    service, _, _ = system
    first = ready(service)
    approve(service, first)
    second = ready(service)
    with pytest.raises(WorkflowError):
        approve(service, second)


def test_source_edit_after_approval_causes_stale_without_writes(system):
    service, provider, store = system
    plan = ready(service)
    run_id = approve(service, plan)
    record = provider.read("notion:T4")
    record["fields"]["EstimateDays"] = 2
    store.put_record(record)
    before = deepcopy(provider.snapshot()["records"])
    service.execute(run_id)
    assert service.run(run_id)["status"] == "STALE"
    assert provider.snapshot()["records"] == before


def test_partial_failure_resumes_after_restart_without_repeating_success(system, monkeypatch):
    service, provider, store = system
    original_write = provider.write

    def fail_github(key, changes, etag=None):
        if key == "github:REL":
            raise ProviderError("GitHub unavailable", kind="auth")
        original_write(key, changes, etag)

    monkeypatch.setattr(provider, "write", fail_github)
    run_id = approve(service, ready(service))
    service.execute(run_id)
    paused = service.run(run_id)
    assert paused["status"] == "PARTIAL"
    assert sum(op["status"] == "VERIFIED" for op in paused["operations"]) == 3
    calendar_etag = provider.read("calendar:M2")["etag"]
    restarted = RelayService(store, SimulationProvider(store), mode="simulated")
    restarted.resume(run_id, "resume-after-auth")
    restarted.execute(run_id)
    assert restarted.run(run_id)["status"] == "VERIFIED"
    assert provider.read("calendar:M2")["etag"] == calendar_etag


def test_timeout_after_provider_applies_write_reconciles_without_duplicate(system, monkeypatch):
    service, provider, _ = system
    original_write = provider.write
    sent = []

    def apply_then_timeout(key, changes, etag=None):
        sent.append(key)
        original_write(key, changes, etag)
        if key == "calendar:M2":
            raise ProviderError("Response lost", kind="uncertain")

    monkeypatch.setattr(provider, "write", apply_then_timeout)
    run_id = approve(service, ready(service))
    service.execute(run_id)
    assert service.run(run_id)["status"] == "VERIFIED"
    assert sent.count("calendar:M2") == 1


def test_success_response_with_wrong_readback_never_reports_success(system, monkeypatch):
    service, provider, _ = system
    original_write = provider.write

    def wrong(key, changes, etag=None):
        if key != "calendar:M2":
            original_write(key, changes, etag)

    monkeypatch.setattr(provider, "write", wrong)
    run_id = approve(service, ready(service))
    service.execute(run_id)
    assert service.run(run_id)["status"] == "VERIFICATION_FAILED"
    assert service.run(run_id)["operations"][0]["status"] == "FAILED"


def test_ambiguous_date_is_not_guessed(system):
    service, _, _ = system
    snapshot = service.snapshot()
    for request in ("Move to next Friday", "Change to 09/10", "Move to 2026-09-18 or 2026-09-24"):
        plan = service.plan(snapshot["id"], request)
        assert plan["status"] == "clarification"
        assert not plan["operations"]


def test_arbitrary_alternative_date_cannot_bypass_server_proposal(system):
    service, _, _ = system
    snapshot = service.snapshot()
    with pytest.raises(WorkflowError):
        service.plan(snapshot["id"], "September 18, 2026", "2026-09-24", None)


def test_reset_cannot_erase_an_unfinished_run(system):
    service, _, _ = system
    approve(service, ready(service))
    with pytest.raises(WorkflowError):
        service.reset()


def test_live_mode_requires_real_model_access_without_simulation_fallback(tmp_path):
    store = Store(tmp_path / "live.sqlite")
    service = RelayService(store, SimulationProvider(store), mode="live")
    snapshot = service.snapshot()
    with pytest.raises(WorkflowError, match="model"):
        service.plan(snapshot["id"], "Move to September 24, 2026")


def test_calendar_version_change_immediately_before_write_requires_review(system, monkeypatch):
    service, provider, store = system
    run_id = approve(service, ready(service))
    original_read = provider.read

    def concurrent_edit(key):
        record = original_read(key)
        if key == "calendar:M2":
            record["etag"] = '"external-new-version"'
            store.put_record(record)
        return record

    monkeypatch.setattr(provider, "read", concurrent_edit)
    service.execute(run_id)
    run = service.run(run_id)
    assert run["status"] == "STALE"
    assert all(op["attempts"] == 0 for op in run["operations"])


def test_fixture_reset_invalidates_old_unapproved_plans(system):
    service, _, _ = system
    plan = ready(service)
    service.reset()
    run_id = approve(service, plan)
    service.execute(run_id)
    assert service.run(run_id)["status"] == "STALE"


def test_crash_after_write_is_reconciled_on_restart(system, monkeypatch):
    service, provider, store = system
    original_write = provider.write

    def crash(key, changes, etag=None):
        original_write(key, changes, etag)
        raise KeyboardInterrupt("Simulated process death")

    monkeypatch.setattr(provider, "write", crash)
    run_id = approve(service, ready(service))
    with pytest.raises(KeyboardInterrupt):
        service.execute(run_id)
    assert service.run(run_id)["operations"][0]["status"] == "IN_FLIGHT"
    etag = provider.read("calendar:M2")["etag"]
    restarted = RelayService(store, SimulationProvider(store), mode="simulated")
    restarted.resume(run_id, "resume-crash")
    restarted.execute(run_id)
    assert restarted.run(run_id)["status"] == "VERIFIED"
    assert provider.read("calendar:M2")["etag"] == etag


def test_exhausted_budget_requires_new_recovery_plan_and_fresh_approval(system, monkeypatch):
    service, provider, _ = system
    original_write = provider.write

    def unavailable(key, changes, etag=None):
        if key == "notion:REL":
            raise ProviderError("Temporarily unavailable", kind="transient")
        original_write(key, changes, etag)

    monkeypatch.setattr(provider, "write", unavailable)
    monkeypatch.setattr("relay.service.time.sleep", lambda _: None)
    run_id = approve(service, ready(service))
    service.execute(run_id)
    assert service.run(run_id)["status"] == "EXHAUSTED"
    assert service.run(run_id)["operations"][-1]["attempts"] == 3
    calendar_before = deepcopy(provider.read("calendar:M2"))
    monkeypatch.setattr(provider, "write", original_write)
    recovery = service.recovery_plan(run_id)
    assert recovery["status"] == "ready"
    assert [op["record_key"] for op in recovery["operations"]] == ["notion:REL"]
    assert provider.read("notion:REL")["fields"]["DeliveryDate"] == "2026-09-25"
    recovered_run = service.approve(recovery["id"], recovery["version"], recovery["hash"], "recovery-approved")["run_id"]
    service.execute(recovered_run)
    assert service.run(recovered_run)["status"] == "VERIFIED"
    assert provider.read("calendar:M2") == calendar_before


def test_recovery_plan_refuses_external_source_edits(system, monkeypatch):
    service, provider, store = system

    def unavailable(*args, **kwargs):
        raise ProviderError("Temporarily unavailable", kind="transient")

    monkeypatch.setattr(provider, "write", unavailable)
    monkeypatch.setattr("relay.service.time.sleep", lambda _: None)
    run_id = approve(service, ready(service))
    service.execute(run_id)
    record = provider.read("notion:T4")
    record["fields"]["EstimateDays"] = 2
    store.put_record(record)
    with pytest.raises(WorkflowError, match="changed"):
        service.recovery_plan(run_id)
