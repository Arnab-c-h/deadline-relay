from copy import deepcopy

from relay.fixtures import build_fixture
from relay.scheduler import propose


def test_github_midnight_readback_does_not_propose_the_milestone_again():
    snapshot = build_fixture()
    plan = propose(snapshot, "2026-09-24")
    assert plan["status"] == "ready"
    for operation in plan["operations"]:
        snapshot["records"][operation["record_key"]]["fields"].update(operation["after"])
    # The live GitHub API returns a date encoded at midnight UTC, even when sent a later time.
    snapshot["records"]["github:REL"]["fields"]["due_on"] = "2026-09-24T00:00:00Z"
    for node in snapshot["nodes"]:
        fields = snapshot["records"][node["record_key"]]["fields"]
        if node["kind"] == "task":
            node.update(start=fields["Schedule"]["start"], end=fields["Schedule"]["end"])
        elif node["kind"] == "meeting":
            node.update(start=fields["start"], end=fields["end"])
        else:
            node.update(start=fields["DeliveryDate"], end=fields["DeliveryDate"])

    verified = propose(snapshot, "2026-09-24")

    assert verified["status"] == "ready"
    assert verified["operations"] == []
    milestone = next(operation for operation in plan["operations"] if operation["record_key"] == "github:REL")
    assert milestone["after"] == {"due_on": "2026-09-24T00:00:00Z"}


def test_fixture_is_complete_normalized_and_clearly_simulated():
    snapshot = build_fixture()

    assert snapshot["mode"] == "simulated"
    assert snapshot["project"] == {
        "id": "demo",
        "name": "Atlas Release 1.0",
        "timezone": "Asia/Kolkata",
        "planning_start": "2026-09-14",
        "horizon_days": 30,
        "deadline": "2026-09-25",
    }
    assert [node["id"] for node in snapshot["nodes"]] == [
        "T1", "T2", "T3", "M1", "T4", "T5", "M2", "REL", "U1", "U2"
    ]
    assert len(snapshot["records"]) == 17
    assert all(record["source_url"] is None for record in snapshot["records"].values())
    assert snapshot["records"]["calendar:M2"]["fields"]["location"] == "Atlas demo room"
    assert snapshot["records"]["github:REL"]["fields"]["due_on"] == "2026-09-25T00:00:00Z"
    assert snapshot["records"]["notion:T1"]["fields"]["Status"] == "Done"
    assert snapshot["records"]["notion:T2"]["fields"]["Status"] == "Not started"


def test_september_18_is_infeasible_and_requires_a_fresh_alternative_plan():
    result = propose(build_fixture(), "2026-09-18")

    assert result["status"] == "infeasible"
    assert result["proposed_date"] == "2026-09-24"
    assert result["operations"] == []
    assert "M1" in " ".join(result["conflicts"])
    assert "September 21" in result["explanation"]


def test_september_24_plan_has_exact_five_normalized_operations():
    result = propose(build_fixture(), "2026-09-24")

    assert result["status"] == "ready"
    assert result["proposed_date"] == "2026-09-24"
    assert [(op["id"], op["record_key"], op["before"], op["after"]) for op in result["operations"]] == [
        (
            "op-1",
            "calendar:M2",
            {"start": "2026-09-25T15:00:00+05:30", "end": "2026-09-25T16:00:00+05:30"},
            {"start": "2026-09-24T15:00:00+05:30", "end": "2026-09-24T16:00:00+05:30"},
        ),
        (
            "op-2",
            "notion:T4",
            {"Schedule": {"start": "2026-09-23", "end": "2026-09-23"}},
            {"Schedule": {"start": "2026-09-22", "end": "2026-09-22"}},
        ),
        (
            "op-3",
            "notion:T5",
            {"Schedule": {"start": "2026-09-24", "end": "2026-09-24"}},
            {"Schedule": {"start": "2026-09-23", "end": "2026-09-23"}},
        ),
        (
            "op-4",
            "github:REL",
            {"due_on": "2026-09-25T00:00:00Z"},
            {"due_on": "2026-09-24T00:00:00Z"},
        ),
        (
            "op-5",
            "notion:REL",
            {"DeliveryDate": "2026-09-25"},
            {"DeliveryDate": "2026-09-24"},
        ),
    ]
    dispositions = {item["id"]: item["disposition"] for item in result["items"]}
    assert dispositions == {
        "T1": "constraint", "T2": "unchanged", "T3": "unchanged", "M1": "constraint",
        "T4": "changed", "T5": "changed", "M2": "changed", "REL": "changed",
        "U1": "unrelated", "U2": "unrelated",
    }


def test_missing_estimate_blocks_without_inventing_a_duration():
    snapshot = build_fixture()
    snapshot["records"]["notion:T4"]["fields"]["EstimateDays"] = None
    next(node for node in snapshot["nodes"] if node["id"] == "T4")["duration_days"] = None

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "blocked"
    assert result["operations"] == []
    assert "T4" in result["explanation"]
    assert "estimate" in result["explanation"].lower()


def test_in_progress_release_task_blocks_replanning():
    snapshot = build_fixture()
    snapshot["records"]["notion:T2"]["fields"]["Status"] = "In progress"

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "blocked"
    assert result["operations"] == []
    assert "T2" in result["explanation"]
    assert "in progress" in result["explanation"].lower()


def test_cycle_and_completed_issue_contradiction_each_block():
    cycle = build_fixture()
    next(node for node in cycle["nodes"] if node["id"] == "T2")["predecessors"] = ["T1", "T5"]
    assert propose(cycle, "2026-09-24")["status"] == "blocked"

    contradiction = build_fixture()
    contradiction["records"]["github:T1"]["fields"]["state"] = "open"
    result = propose(contradiction, "2026-09-24")
    assert result["status"] == "blocked"
    assert "T1" in result["explanation"]
    assert "contradict" in result["explanation"].lower()


def test_busy_calendar_record_is_preserved_and_pushes_earliest_date():
    snapshot = build_fixture()
    snapshot["records"]["calendar:busy-demo"] = {
        "key": "calendar:busy-demo",
        "provider": "calendar",
        "resource_id": "busy-demo",
        "name": "Busy day",
        "source_url": None,
        "fields": {
            "start": "2026-09-24T10:00:00+05:30",
            "end": "2026-09-24T17:00:00+05:30",
            "summary": "Busy day",
            "description": "Simulated blocking record",
            "location": "",
            "transparency": "opaque",
            "recurring": False,
            "all_day": False,
            "fixed": True,
        },
        "etag": "busy-v1",
    }

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "infeasible"
    assert result["proposed_date"] == "2026-09-25"
    assert result["operations"] == []
    assert "Busy day" in result["explanation"]
    assert "2026-09-24" in result["explanation"]
    assert snapshot["records"]["calendar:busy-demo"]["fields"]["start"] == "2026-09-24T10:00:00+05:30"


def test_fixed_meeting_overlap_blocks_planning():
    snapshot = build_fixture()
    snapshot["records"]["calendar:fixed-conflict"] = {
        "key": "calendar:fixed-conflict", "provider": "calendar", "resource_id": "fixed-conflict",
        "name": "Fixed conflict", "source_url": None,
        "fields": {"start": "2026-09-21T11:30:00+05:30", "end": "2026-09-21T12:30:00+05:30",
                   "summary": "Fixed conflict", "description": "Simulated", "location": "",
                   "transparency": "opaque", "recurring": False, "all_day": False, "fixed": True},
        "etag": "fixed-v1",
    }

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "blocked"
    assert "M1" in result["explanation"]
    assert "conflict" in result["explanation"].lower()


def test_weekend_deadline_is_preserved_in_project_timezone():
    result = propose(build_fixture(), "2026-09-26")

    assert result["status"] == "ready"
    assert result["requested_date"] == "2026-09-26"
    assert result["proposed_date"] == "2026-09-26"
    milestone = next(op for op in result["operations"] if op["record_key"] == "github:REL")
    assert milestone["after"] == {"due_on": "2026-09-26T00:00:00Z"}


def test_propose_does_not_mutate_snapshot_or_unrelated_records():
    snapshot = build_fixture()
    before = deepcopy(snapshot)

    propose(snapshot, "2026-09-24")

    assert snapshot == before
    assert snapshot["records"]["notion:U1"] == before["records"]["notion:U1"]
    assert snapshot["records"]["calendar:U2"] == before["records"]["calendar:U2"]


def test_recurring_movable_meeting_is_unsupported_only_when_an_edit_is_required():
    snapshot = build_fixture()
    snapshot["records"]["calendar:M2"]["fields"]["recurring"] = True

    changed = propose(snapshot, "2026-09-24")
    unchanged = propose(snapshot, "2026-09-25")

    assert changed["status"] == "unsupported"
    assert changed["operations"] == []
    assert "recurring" in changed["explanation"].lower()
    assert unchanged["status"] == "ready"


def test_every_changed_mutable_task_gets_an_operation_in_topological_order():
    snapshot = build_fixture()
    t2 = next(node for node in snapshot["nodes"] if node["id"] == "T2")
    t2["start"], t2["end"] = "2026-09-17", "2026-09-18"
    snapshot["records"]["notion:T2"]["fields"]["Schedule"] = {
        "start": "2026-09-17", "end": "2026-09-18"
    }

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "ready"
    task_operations = [op for op in result["operations"] if op["record_key"].startswith("notion:T")]
    assert [op["record_key"] for op in task_operations] == ["notion:T2", "notion:T4", "notion:T5"]
    assert task_operations[0]["after"] == {
        "Schedule": {"start": "2026-09-16", "end": "2026-09-17"}
    }


def test_old_movable_meeting_interval_does_not_conflict_with_fixed_meeting():
    snapshot = build_fixture()
    m2 = next(node for node in snapshot["nodes"] if node["id"] == "M2")
    m2["start"], m2["end"] = "2026-09-21T11:00:00+05:30", "2026-09-21T12:00:00+05:30"
    snapshot["records"]["calendar:M2"]["fields"].update(start=m2["start"], end=m2["end"])

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "ready"
    m2_operation = next(op for op in result["operations"] if op["record_key"] == "calendar:M2")
    assert m2_operation["after"] == {
        "start": "2026-09-24T11:00:00+05:30", "end": "2026-09-24T12:00:00+05:30"
    }


def test_fixed_release_blocks_a_requested_date_change():
    snapshot = build_fixture()
    next(node for node in snapshot["nodes"] if node["id"] == "REL")["fixed"] = True

    result = propose(snapshot, "2026-09-28")

    assert result["status"] == "blocked"
    assert result["operations"] == []
    assert "REL" in result["explanation"]
    assert "fixed" in result["explanation"].lower()


def test_zero_duration_meeting_blocks_planning():
    snapshot = build_fixture()
    m2 = next(node for node in snapshot["nodes"] if node["id"] == "M2")
    m2["end"] = m2["start"]
    snapshot["records"]["calendar:M2"]["fields"]["end"] = m2["start"]

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "blocked"
    assert result["operations"] == []
    assert "duration" in result["explanation"].lower()


def test_task_schedule_must_match_its_inclusive_working_day_duration():
    snapshot = build_fixture()
    t2 = next(node for node in snapshot["nodes"] if node["id"] == "T2")
    t2["end"] = t2["start"]
    snapshot["records"]["notion:T2"]["fields"]["Schedule"]["end"] = t2["start"]

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "blocked"
    assert result["operations"] == []
    assert "T2" in result["explanation"]
    assert "duration" in result["explanation"].lower()


def test_naive_meeting_timestamp_blocks_timezone_sensitive_planning():
    snapshot = build_fixture()
    m2 = next(node for node in snapshot["nodes"] if node["id"] == "M2")
    m2["start"] = "2026-09-25T15:00:00"
    snapshot["records"]["calendar:M2"]["fields"]["start"] = m2["start"]

    result = propose(snapshot, "2026-09-24")

    assert result["status"] == "blocked"
    assert result["operations"] == []
    assert "timezone" in result["explanation"].lower()
def test_busy_evidence_preserves_source_link():
    snapshot = build_fixture()
    snapshot["records"]["calendar:busy-proof"] = {
        "key": "calendar:busy-proof", "provider": "calendar", "resource_id": "busy-proof",
        "name": "Availability evidence", "source_url": "https://calendar.google.com/calendar/event?eid=proof",
        "fields": {"start": "2026-09-24T10:00:00+05:30", "end": "2026-09-24T17:00:00+05:30"},
    }
    result = propose(snapshot, "2026-09-24")
    assert result["status"] == "infeasible"
    evidence = next(item for item in result["items"] if item["id"] == "calendar:busy-proof")
    assert evidence["source_url"].endswith("eid=proof")
    assert evidence["before"] == evidence["after"]
