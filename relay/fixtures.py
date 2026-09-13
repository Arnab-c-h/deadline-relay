"""Canonical, fictional Deadline Relay fixture."""

from __future__ import annotations

import hashlib
import json


def _record(key, provider, resource_id, name, fields, *, etag=None):
    return {
        "key": key,
        "provider": provider,
        "resource_id": resource_id,
        "name": name,
        "source_url": None,
        "fields": fields,
        "etag": etag,
    }


def build_fixture() -> dict:
    """Return a fresh, complete normalized snapshot of fictional records."""
    task_specs = {
        "T1": ("Requirements approved", "2026-09-11", "2026-09-11", 1, True, "Done", [], None),
        "T2": ("Implement export API", "2026-09-16", "2026-09-17", 2, False, "Not started", ["T1"], "2026-09-14"),
        "T3": ("Integration testing", "2026-09-18", "2026-09-18", 1, False, "Not started", ["T2"], "2026-09-14"),
        "T4": ("Apply review checklist", "2026-09-23", "2026-09-23", 1, False, "Not started", ["M1"], "2026-09-14"),
        "T5": ("Release validation", "2026-09-24", "2026-09-24", 1, False, "Not started", ["T4"], "2026-09-14"),
        "U1": ("Refresh careers-page copy", "2026-09-22", "2026-09-22", 1, False, "Not started", [], "2026-09-14"),
    }
    records = {}
    for item_id, (name, start, end, estimate, fixed, status, predecessors, not_before) in task_specs.items():
        records[f"notion:{item_id}"] = _record(
            f"notion:{item_id}", "notion", f"sim-notion-{item_id.lower()}", name,
            {"Schedule": {"start": start, "end": end}, "EstimateDays": estimate, "Fixed": fixed,
             "Status": status, "Predecessors": predecessors, "NotBefore": not_before, "Name": name},
            etag=f"fixture-{item_id.lower()}-v1",
        )
        state = "closed" if item_id == "T1" else "open"
        milestone = None if item_id == "U1" else 1
        records[f"github:{item_id}"] = _record(
            f"github:{item_id}", "github", f"sim-issue-{item_id.lower()}", name,
            {"state": state, "milestone": milestone, "title": name}, etag=f"fixture-gh-{item_id.lower()}-v1",
        )

    records["notion:REL"] = _record(
        "notion:REL", "notion", "sim-notion-rel", "Atlas Release 1.0",
        {"DeliveryDate": "2026-09-25", "AcceptedPlan": "fixture-baseline", "Name": "Atlas Release 1.0"},
        etag="fixture-rel-v1",
    )
    records["github:REL"] = _record(
        "github:REL", "github", "sim-milestone-1", "Atlas Release 1.0",
        {"due_on": "2026-09-25T12:30:00Z", "title": "Atlas Release 1.0",
         "description": "Fictional Atlas release milestone"}, etag="fixture-gh-rel-v1",
    )

    calendar_specs = {
        "M1": ("Security review", "2026-09-21T11:00:00+05:30", "2026-09-21T12:00:00+05:30", True,
               "Fixed security review for the fictional Atlas release"),
        "M2": ("Release sign-off", "2026-09-25T15:00:00+05:30", "2026-09-25T16:00:00+05:30", False,
               "Movable sign-off for the fictional Atlas release"),
        "U2": ("Owner appointment", "2026-09-23T10:00:00+05:30", "2026-09-23T11:00:00+05:30", True,
               "Unrelated fictional appointment"),
    }
    for item_id, (name, start, end, fixed, description) in calendar_specs.items():
        records[f"calendar:{item_id}"] = _record(
            f"calendar:{item_id}", "calendar", f"sim-calendar-{item_id.lower()}", name,
            {"start": start, "end": end, "summary": name, "description": description,
             "location": "Atlas demo room", "transparency": "opaque", "recurring": False,
             "all_day": False, "fixed": fixed}, etag=f"fixture-cal-{item_id.lower()}-v1",
        )

    nodes = []
    for item_id in ("T1", "T2", "T3"):
        spec = task_specs[item_id]
        nodes.append(_task_node(item_id, spec))
    nodes.append(_meeting_node("M1", calendar_specs["M1"], ["T3"]))
    for item_id in ("T4", "T5"):
        nodes.append(_task_node(item_id, task_specs[item_id]))
    nodes.append(_meeting_node("M2", calendar_specs["M2"], ["T5"]))
    nodes.append({
        "id": "REL", "name": "Atlas Release 1.0", "kind": "release", "record_key": "notion:REL",
        "predecessors": ["M2"], "start": "2026-09-25", "end": "2026-09-25", "duration_days": None,
        "fixed": False, "completed": False, "not_before": None, "issue_state": None, "source_url": None,
    })
    nodes.append(_task_node("U1", task_specs["U1"]))
    nodes.append(_meeting_node("U2", calendar_specs["U2"], []))

    canonical = json.dumps({"nodes": nodes, "records": records}, sort_keys=True, separators=(",", ":"))
    return {
        "id": "fixture-snapshot-v1",
        "captured_at": "2026-09-13T22:00:00+05:30",
        "mode": "simulated",
        "project": {"id": "demo", "name": "Atlas Release 1.0", "timezone": "Asia/Kolkata",
                    "planning_start": "2026-09-14", "horizon_days": 30, "deadline": "2026-09-25"},
        "nodes": nodes,
        "records": records,
        "config_hash": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def _task_node(item_id, spec):
    name, start, end, estimate, fixed, status, predecessors, not_before = spec
    return {
        "id": item_id, "name": name, "kind": "task", "record_key": f"notion:{item_id}",
        "predecessors": list(predecessors), "start": start, "end": end, "duration_days": estimate,
        "fixed": fixed, "completed": status == "Done", "not_before": not_before,
        "issue_state": "closed" if item_id == "T1" else "open", "source_url": None,
    }


def _meeting_node(item_id, spec, predecessors):
    name, start, end, fixed, _ = spec
    return {
        "id": item_id, "name": name, "kind": "meeting", "record_key": f"calendar:{item_id}",
        "predecessors": list(predecessors), "start": start, "end": end, "duration_days": None,
        "fixed": fixed, "completed": False, "not_before": None, "issue_state": None, "source_url": None,
    }
