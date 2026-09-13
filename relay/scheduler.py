"""Deterministic scheduling for the bounded Deadline Relay model."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def propose(snapshot: dict, requested_date: str) -> dict:
    """Build a write-free proposal for an absolute delivery date."""
    base = _base_result(requested_date)
    try:
        requested = date.fromisoformat(requested_date)
    except (TypeError, ValueError):
        return _blocked(base, "Cannot evaluate: requested_date must be an ISO date.")

    project = snapshot.get("project", {})
    try:
        zone = ZoneInfo(project["timezone"])
        planning_start = date.fromisoformat(project["planning_start"])
        horizon_days = int(project["horizon_days"])
    except (KeyError, TypeError, ValueError):
        return _blocked(base, "Cannot evaluate: project scheduling configuration is incomplete.")
    working_dates = _working_dates(planning_start, horizon_days)
    if not working_dates:
        return _blocked(base, "Cannot evaluate: the working-date horizon is empty.")
    horizon_end = working_dates[-1]
    if requested < planning_start or requested > horizon_end:
        base.update(status="unsupported", explanation="Requested date is outside the configured horizon.")
        return base

    nodes = {node.get("id"): node for node in snapshot.get("nodes", []) if node.get("id")}
    records = snapshot.get("records", {})
    error = _validate(nodes, records)
    if error:
        return _blocked(base, error)
    try:
        ancestors = _ancestors(nodes, "REL")
        order = _topological(nodes, ancestors)
        busy = _busy_intervals(records, zone, exclude_keys={"calendar:M2"})
        domains = {node_id: _domain(nodes[node_id], working_dates, horizon_end, zone, busy)
                   for node_id in order}
    except ValueError as exc:
        return _blocked(base, f"Cannot evaluate: {exc}")

    for node_id in order:
        if not domains[node_id]:
            return _blocked(base, f"Cannot evaluate {node_id}: no supported candidate exists in the horizon.")
    fixed_conflict = _fixed_calendar_conflict(nodes, records, zone)
    if fixed_conflict:
        return _blocked(base, fixed_conflict)
    if nodes["REL"]["fixed"] and requested != date.fromisoformat(nodes["REL"]["start"]):
        return _blocked(base, "Cannot evaluate: fixed release REL cannot move to the requested date.")

    earliest = {}
    for node_id in order:
        predecessor_end = max((earliest[p][1] for p in nodes[node_id]["predecessors"]), default=None)
        candidates = [interval for interval in domains[node_id]
                      if predecessor_end is None or interval[0] >= predecessor_end]
        if not candidates:
            if nodes[node_id]["fixed"]:
                return _blocked(base, f"Cannot evaluate: fixed node {node_id} contradicts its dependency chain.")
            return _blocked(base, f"Cannot evaluate {node_id}: dependency chain exceeds the horizon.")
        earliest[node_id] = candidates[0]

    earliest_date = earliest["REL"][0].date()
    if earliest_date > requested:
        conflicts = _infeasibility_evidence(nodes, records, requested, zone, ancestors)
        friendly_date = f"{earliest_date.strftime('%B')} {earliest_date.day}"
        base.update(
            status="infeasible", proposed_date=earliest_date.isoformat(), conflicts=conflicts,
            explanation=("Requested deadline infeasible: " + " ".join(conflicts) + " "
                         f"The earliest feasible date under this model is {friendly_date}."),
            items=_items(nodes, {}, ancestors, records),
            assumptions=_assumptions(project),
        )
        return base

    placed = {"REL": _release_interval(requested, zone)}
    successors = _successors(nodes, ancestors)
    for node_id in reversed(order[:-1]):
        node = nodes[node_id]
        latest_start = min((placed[s][0] for s in successors[node_id]), default=placed["REL"][0])
        candidates = [interval for interval in domains[node_id]
                      if interval[0] >= earliest[node_id][0] and interval[1] <= latest_start]
        if not candidates:
            return _blocked(base, f"Cannot evaluate {node_id}: no candidate satisfies the requested deadline.")
        original = _node_interval(node, zone)
        if node["kind"] == "meeting":
            # Preserve its wall-clock slot before choosing the closest working date.
            key = lambda x, original=original: (
                _time_displacement(x[0], original[0]),
                abs((x[0].date() - original[0].date()).days),
                x[0],
            )
        else:
            key = lambda x, original=original: (abs((x[0] - original[0]).total_seconds()), x[0])
        placed[node_id] = min(candidates, key=key)

    m2_fields = records.get("calendar:M2", {}).get("fields", {})
    if placed.get("M2") != _node_interval(nodes["M2"], zone) and (
        m2_fields.get("recurring") or m2_fields.get("all_day")
    ):
        base.update(
            status="unsupported",
            proposed_date=requested.isoformat(),
            explanation="Moving a recurring or all-day meeting is unsupported.",
            items=_items(nodes, placed, ancestors, records),
            assumptions=_assumptions(project),
        )
        return base

    operations = _operations(snapshot, placed, requested, zone)
    base.update(
        status="ready", proposed_date=requested.isoformat(),
        explanation="Feasible under supplied assumptions.", conflicts=[], operations=operations,
        items=_items(nodes, placed, ancestors, records), assumptions=_assumptions(project),
    )
    return base


def _base_result(requested):
    return {"status": "blocked", "requested_date": requested, "proposed_date": None, "explanation": "",
            "conflicts": [], "operations": [], "items": [], "assumptions": []}


def _blocked(base, explanation):
    base.update(status="blocked", explanation=explanation, operations=[])
    return base


def _validate(nodes, records):
    if "REL" not in nodes:
        return "Cannot evaluate: release node REL is missing."
    for node_id, node in nodes.items():
        for predecessor in node.get("predecessors", []):
            if predecessor not in nodes:
                return f"Cannot evaluate {node_id}: predecessor {predecessor} is missing."
        if node.get("kind") == "task" and not node.get("completed"):
            duration = node.get("duration_days")
            notion = records.get(node.get("record_key"), {}).get("fields", {})
            if notion.get("Status") == "In progress":
                return f"Cannot evaluate {node_id}: in progress task replanning is unsupported."
            if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0 or notion.get("EstimateDays") != duration:
                return f"Cannot evaluate {node_id}: a positive matching estimate is required."
        if node.get("kind") == "task":
            try:
                start, end = date.fromisoformat(node["start"]), date.fromisoformat(node["end"])
            except (KeyError, TypeError, ValueError):
                return f"Cannot evaluate {node_id}: task schedule dates are invalid."
            duration = node.get("duration_days")
            if start > end or start.weekday() >= 5 or end.weekday() >= 5 or (
                isinstance(duration, int) and _inclusive_working_days(start, end) != duration
            ):
                return f"Cannot evaluate {node_id}: task date range does not match its duration."
        if node.get("kind") == "meeting":
            try:
                start = _parse_datetime(node["start"])
                end = _parse_datetime(node["end"])
            except (KeyError, TypeError, ValueError):
                return f"Cannot evaluate {node_id}: meeting timestamps require an explicit timezone offset."
            if end <= start:
                return f"Cannot evaluate {node_id}: meeting duration must be positive."
        if node.get("kind") == "task":
            issue = records.get(f"github:{node_id}", {}).get("fields", {}).get("state")
            if issue and ((node.get("completed") and issue != "closed") or (not node.get("completed") and issue == "closed")):
                return f"Cannot evaluate {node_id}: completed status and issue state contradict each other."
    try:
        _topological(nodes, set(nodes))
    except ValueError:
        return "Cannot evaluate: dependency cycle detected."
    return None


def _ancestors(nodes, root):
    result = set()
    stack = [root]
    while stack:
        node_id = stack.pop()
        if node_id in result:
            continue
        result.add(node_id)
        stack.extend(nodes[node_id]["predecessors"])
    return result


def _topological(nodes, included):
    indegree = {node_id: 0 for node_id in included}
    successors = {node_id: [] for node_id in included}
    for node_id in included:
        for predecessor in nodes[node_id].get("predecessors", []):
            if predecessor in included:
                indegree[node_id] += 1
                successors[predecessor].append(node_id)
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for successor in sorted(successors[node_id]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                ready.append(successor)
                ready.sort()
    if len(order) != len(included):
        raise ValueError("dependency cycle detected")
    return order


def _successors(nodes, included):
    result = {node_id: [] for node_id in included}
    for node_id in included:
        for predecessor in nodes[node_id]["predecessors"]:
            if predecessor in result:
                result[predecessor].append(node_id)
    return result


def _working_dates(start, count):
    dates, current = [], start
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def _inclusive_working_days(start, end):
    count, current = 0, start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += timedelta(days=1)
    return count


def _domain(node, working_dates, horizon_end, zone, busy):
    if node["fixed"] or node["completed"]:
        return [_node_interval(node, zone)]
    if node["kind"] == "task":
        duration = node["duration_days"]
        not_before = date.fromisoformat(node["not_before"]) if node.get("not_before") else working_dates[0]
        candidates = []
        for index, day in enumerate(working_dates):
            if day < not_before or index + duration > len(working_dates):
                continue
            segment = working_dates[index:index + duration]
            candidates.append((datetime.combine(day, time(9), zone), datetime.combine(segment[-1], time(18), zone)))
        return candidates
    if node["kind"] == "meeting":
        original = _node_interval(node, zone)
        duration = original[1] - original[0]
        candidates = []
        for day in working_dates:
            current = datetime.combine(day, time(10), zone)
            close = datetime.combine(day, time(17), zone)
            while current + duration <= close:
                interval = (current, current + duration)
                if not any(_overlap(interval, blocked) for blocked in busy):
                    candidates.append(interval)
                current += timedelta(minutes=30)
        return candidates
    if node["kind"] == "release":
        candidates, day = [], working_dates[0]
        while day <= horizon_end:
            candidates.append(_release_interval(day, zone))
            day += timedelta(days=1)
        return candidates
    raise ValueError(f"unsupported node kind for {node['id']}")


def _node_interval(node, zone):
    if node["kind"] == "task":
        return (datetime.combine(date.fromisoformat(node["start"]), time(9), zone),
                datetime.combine(date.fromisoformat(node["end"]), time(18), zone))
    if node["kind"] == "meeting":
        return (_parse_datetime(node["start"], zone), _parse_datetime(node["end"], zone))
    return _release_interval(date.fromisoformat(node["start"]), zone)


def _release_interval(day, zone):
    instant = datetime.combine(day, time(18), zone)
    return instant, instant


def _parse_datetime(value, zone=None):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp requires an explicit timezone offset")
    return parsed if zone is None else parsed.astimezone(zone)


def _busy_intervals(records, zone, exclude_keys):
    busy = []
    for key, record in records.items():
        if record.get("provider") != "calendar" or key in exclude_keys:
            continue
        fields = record.get("fields", {})
        if fields.get("transparency", "opaque") == "transparent" or fields.get("cancelled"):
            continue
        start, end = fields.get("start"), fields.get("end")
        if not start or not end:
            continue
        if fields.get("all_day") or ("T" not in start and "T" not in end):
            busy.append((datetime.combine(date.fromisoformat(start), time.min, zone),
                         datetime.combine(date.fromisoformat(end), time.min, zone)))
        else:
            busy.append((_parse_datetime(start, zone), _parse_datetime(end, zone)))
    return busy


def _fixed_calendar_conflict(nodes, records, zone):
    fixed_meetings = [node for node in nodes.values() if node["kind"] == "meeting" and node["fixed"]]
    movable_keys = {node["record_key"] for node in nodes.values()
                    if node["kind"] == "meeting" and not node["fixed"]}
    for node in fixed_meetings:
        interval = _node_interval(node, zone)
        busy = _busy_intervals(records, zone, exclude_keys=movable_keys | {node["record_key"]})
        if any(_overlap(interval, other) for other in busy):
            return f"Cannot evaluate: fixed meeting {node['id']} has a calendar conflict."
    return None


def _overlap(left, right):
    return left[0] < right[1] and right[0] < left[1]


def _time_displacement(left, right):
    return abs((left.hour * 60 + left.minute) - (right.hour * 60 + right.minute))


def _operations(snapshot, placed, requested, zone):
    records = snapshot["records"]
    changes = []
    m2_start, m2_end = placed["M2"]
    _append_change(changes, records["calendar:M2"],
                   {"start": records["calendar:M2"]["fields"]["start"], "end": records["calendar:M2"]["fields"]["end"]},
                   {"start": m2_start.isoformat(), "end": m2_end.isoformat()})
    nodes = {node["id"]: node for node in snapshot["nodes"]}
    release_graph = _ancestors(nodes, "REL")
    task_ids = [node_id for node_id in _topological(nodes, release_graph)
                if nodes[node_id]["kind"] == "task"
                and not nodes[node_id]["fixed"] and not nodes[node_id]["completed"]]
    for item_id in task_ids:
        start, end = placed[item_id]
        before = {"Schedule": records[f"notion:{item_id}"]["fields"]["Schedule"]}
        after = {"Schedule": {"start": start.date().isoformat(), "end": end.date().isoformat()}}
        _append_change(changes, records[f"notion:{item_id}"], before, after)
    due = datetime.combine(requested, time(18), zone).astimezone(UTC).isoformat().replace("+00:00", "Z")
    _append_change(changes, records["github:REL"], {"due_on": records["github:REL"]["fields"]["due_on"]}, {"due_on": due})
    _append_change(changes, records["notion:REL"], {"DeliveryDate": records["notion:REL"]["fields"]["DeliveryDate"]},
                   {"DeliveryDate": requested.isoformat()})
    for index, operation in enumerate(changes, 1):
        operation["id"] = f"op-{index}"
    return changes


def _append_change(changes, record, before, after):
    if before == after:
        return
    changes.append({"id": "", "record_key": record["key"], "provider": record["provider"],
                    "resource_id": record["resource_id"], "name": record["name"],
                    "source_url": record.get("source_url"), "before": before, "after": after})


def _items(nodes, placed, ancestors, records):
    result = []
    for node in nodes.values():
        if node["id"] not in ancestors:
            disposition = "unrelated"
        elif node["fixed"] or node["completed"]:
            disposition = "constraint"
        elif node["id"] in placed and _display_interval(node, placed[node["id"]]) != _display_before(node):
            disposition = "changed"
        else:
            disposition = "unchanged"
        result.append({"id": node["id"], "name": node["name"], "kind": node["kind"],
                       "before": _display_before(node),
                       "after": _display_interval(node, placed[node["id"]]) if node["id"] in placed else _display_before(node),
                       "disposition": disposition, "source_url": node.get("source_url")})
    node_keys = {node["record_key"] for node in nodes.values()}
    for key, record in records.items():
        fields = record.get("fields", {})
        if key in node_keys or record.get("provider") != "calendar":
            continue
        if fields.get("cancelled") or fields.get("transparency") == "transparent":
            continue
        interval = f"{fields.get('start', 'Unknown')} to {fields.get('end', 'Unknown')}"
        result.append({"id": key, "name": record.get("name", key), "kind": "meeting",
                       "before": interval, "after": interval, "disposition": "unrelated",
                       "source_url": record.get("source_url")})
    return result


def _display_before(node):
    return node["start"] if node["start"] == node["end"] else f"{node['start']} to {node['end']}"


def _display_interval(node, interval):
    if node["kind"] == "meeting":
        return f"{interval[0].isoformat()} to {interval[1].isoformat()}"
    if node["kind"] == "release":
        return interval[0].date().isoformat()
    start, end = interval[0].date().isoformat(), interval[1].date().isoformat()
    return start if start == end else f"{start} to {end}"


def _assumptions(project):
    return [f"Timezone: {project['timezone']}", "Working days: Monday-Friday; no holidays",
            "Tasks use supplied whole-working-day estimates", "One owner calendar and at most one movable meeting"]


def _infeasibility_evidence(nodes, records, requested, zone, ancestors):
    evidence = []
    for node_id in sorted(ancestors):
        node = nodes[node_id]
        if node["fixed"] and node["kind"] != "release":
            interval = _node_interval(node, zone)
            if interval[0].date() > requested:
                friendly = f"{interval[0].strftime('%B')} {interval[0].day}"
                evidence.append(f"{node_id} fixed constraint is on {friendly} ({interval[0].date().isoformat()}).")
    meeting_open = datetime.combine(requested, time(10), zone)
    meeting_close = datetime.combine(requested, time(17), zone)
    for key, record in sorted(records.items()):
        if record.get("provider") != "calendar" or key == "calendar:M2":
            continue
        fields = record.get("fields", {})
        if fields.get("transparency", "opaque") == "transparent" or fields.get("cancelled"):
            continue
        try:
            intervals = _busy_intervals({key: record}, zone, exclude_keys=set())
        except ValueError:
            continue
        if any(_overlap((meeting_open, meeting_close), interval) for interval in intervals):
            evidence.append(f"{record.get('name', key)} blocks meeting availability on {requested.isoformat()}.")
    return evidence or ["The dependency and availability constraints extend past the requested date."]
