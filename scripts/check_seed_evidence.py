"""Validate captured real-provider seed read-backs; this is not an agent E2E run.

Run after saving fresh MCP responses to data/live-readback.json and GitHub CLI
responses to data/github-readback.json and data/github-milestone-readback.json.
No network calls or writes to the providers are made by this checker.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8-sig"))


def check(condition, message):
    if not condition:
        raise ValueError(message)


def rich(prop):
    return "".join(item["plain_text"] for item in prop[prop["type"]])


def main():
    manifest = read("live-test-manifest.json")
    results = read("live-readback.json")
    check(all(item["response"]["successful"] for item in results), "Provider read-back failed")
    pages = {item["response"]["data"]["id"]: item["response"]["data"] for item in results
             if item["tool_slug"] == "NOTION_RETRIEVE_PAGE"}
    events = {item["response"]["data"]["id"]: item["response"]["data"] for item in results
              if item["tool_slug"] == "GOOGLECALENDAR_EVENTS_GET"}
    check(set(pages) == set(manifest["notion"]["records"].values()), "Notion record coverage differs")
    check(set(events) == set(manifest["calendar"]["events"].values()), "Calendar record coverage differs")
    predecessors = {"T1": "", "T2": "T1", "T3": "T2", "M1": "T3", "T4": "M1",
                    "T5": "T4", "M2": "T5", "REL": "M2", "U1": ""}
    dates = {"T1": ("11", "11", 1), "T2": ("16", "17", 2), "T3": ("18", "18", 1),
             "T4": ("23", "23", 1), "T5": ("24", "24", 1), "U1": ("22", "22", 1)}
    for logical, page_id in manifest["notion"]["records"].items():
        page = pages[page_id]
        p = page["properties"]
        check(not page["archived"] and not page["in_trash"], f"{logical} is archived")
        check(page["parent"]["database_id"] == manifest["notion"]["database_id"], "Wrong Notion parent")
        check(rich(p["Item ID"]) == logical, f"Wrong logical ID: {logical}")
        check(p["Predecessors"]["type"] == "rich_text", "Unexpected dependency type")
        check(rich(p["Predecessors"]) == predecessors[logical], f"Wrong dependencies: {logical}")
        check(p["Fixed"]["checkbox"] == (logical in {"T1", "M1"}), f"Wrong fixed flag: {logical}")
        check(p["Status"]["status"]["name"] == ("Done" if logical == "T1" else "Not started"),
              f"Wrong status: {logical}")
        if logical in dates:
            start, end, estimate = dates[logical]
            date = p["Schedule"]["date"]
            check(date["start"] == f"2026-09-{start}" and (date["end"] or date["start"]) == f"2026-09-{end}",
                  f"Wrong dates: {logical}")
            check(p["Estimate days"]["number"] == estimate, f"Wrong estimate: {logical}")
            not_before = p["Not before"]["date"]
            check(not_before is None if logical == "T1" else not_before["start"] == "2026-09-14",
                  f"Wrong not-before constraint: {logical}")
        if logical == "REL":
            check(p["Delivery date"]["date"]["start"] == "2026-09-25", "Release date differs")
            check(rich(p["Accepted plan"]) == "baseline", "Baseline marker differs")
    times = {"M1": ("21", "11", "12"), "M2": ("25", "15", "16"), "U2": ("23", "10", "11")}
    for logical, event_id in manifest["calendar"]["events"].items():
        event = events[event_id]
        day, start, end = times[logical]
        for key, hour in (("start", start), ("end", end)):
            check(event[key]["dateTime"] == f"2026-09-{day}T{hour}:00:00+05:30", f"Wrong {logical} {key}")
            check(event[key]["timeZone"] == "Asia/Kolkata", f"Wrong timezone: {logical}")
        check(event["organizer"]["email"] == manifest["calendar"]["calendar_id"], "Wrong calendar")
        check(not event.get("attendees") and not event.get("recurrence"), "Unexpected guests or recurrence")
        check(not event.get("conferenceData") and not event.get("hangoutLink"), "Unexpected conference")
        check(event["visibility"] == "private", "Unexpected event visibility")
        check(event["reminders"]["useDefault"] is False and not event["reminders"].get("overrides"),
              "Test reminders are not disabled")
    issues = {issue["number"]: issue for issue in read("github-readback.json")}
    check(set(issues) == set(manifest["github"]["issues"].values()), "GitHub issue coverage differs")
    for logical, number in manifest["github"]["issues"].items():
        issue = issues[number]
        check(issue["state"] == ("closed" if logical == "T1" else "open"), f"Wrong issue state: {logical}")
        check((issue["milestone"] or {}).get("number") == (None if logical == "U1" else 1),
              f"Wrong issue milestone: {logical}")
    check(read("github-milestone-readback.json")["due_on"] == "2026-09-25T00:00:00Z", "Milestone date differs")
    print("PASS: 9 Notion rows, 6 GitHub issues, 1 milestone, and 3 Calendar events match the real seed baseline.")
    print("Captured provider read-backs only. Application-driven model, approval, execution and deployment remain unverified.")


if __name__ == "__main__":
    main()
