import json
from pathlib import Path

import httpx
import pytest

from relay.providers import LiveProvider, ProviderError


def _config(tmp_path: Path) -> Path:
    data = {
        "project": {
            "id": "demo",
            "name": "Atlas Release 1.0",
            "timezone": "Asia/Kolkata",
            "planning_start": "2026-09-14",
            "horizon_days": 30,
            "deadline": "2026-09-25",
        },
        "notion": {
            "data_source_id": "ds-1",
            "properties": {
                "name": "Name",
                "schedule": "Schedule",
                "estimate_days": "EstimateDays",
                "fixed": "Fixed",
                "status": "Status",
                "predecessors": "Predecessors",
                "not_before": "NotBefore",
                "delivery_date": "DeliveryDate",
                "accepted_plan": "AcceptedPlan",
            },
            "records": {"T1": "page-t1", "M1": "page-m1", "M2": "page-m2", "REL": "page-rel"},
        },
        "github": {"owner": "acme", "repo": "atlas", "milestone_number": 7, "issues": {"T1": 11}},
        "calendar": {
            "calendar_id": "owned@example.test",
            "events": {"M1": "event-m1", "M2": "event-m2", "U2": "event-u2"},
        },
        "nodes": {
            "T1": {
                "name": "Requirements approved",
                "kind": "task",
                "record_key": "notion:T1",
                "predecessors": [],
                "duration_days": 1,
                "issue_record_key": "github:T1",
            },
            "M1": {
                "kind": "meeting",
                "record_key": "calendar:M1",
                "metadata_record_key": "notion:M1",
            },
            "M2": {
                "kind": "meeting",
                "record_key": "calendar:M2",
                "metadata_record_key": "notion:M2",
            },
            "REL": {
                "kind": "release",
                "record_key": "notion:REL",
                "issue_record_key": "github:REL",
            },
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _provider(tmp_path, monkeypatch, handler):
    monkeypatch.setenv("GITHUB_TOKEN", "github-secret")
    monkeypatch.setenv("NOTION_TOKEN", "notion-secret")
    monkeypatch.setenv("GOOGLE_TOKEN_PATH", str(tmp_path / "google.json"))
    (tmp_path / "google.json").write_text(json.dumps({"token": "google-secret"}), encoding="utf-8")
    return LiveProvider(_config(tmp_path), client=httpx.Client(transport=httpx.MockTransport(handler)))


def _predecessor_provider(tmp_path, monkeypatch, *, mode=None, schema_type="rich_text",
                          page_type=None, value="T1, M2"):
    page_type = page_type or schema_type
    schema = {"Name": {"type": "title"}, "Schedule": {"type": "date"},
              "EstimateDays": {"type": "number"}, "Fixed": {"type": "checkbox"},
              "Status": {"type": "status"}, "Predecessors": {"type": schema_type},
              "NotBefore": {"type": "date"}, "DeliveryDate": {"type": "date"},
              "AcceptedPlan": {"type": "rich_text"}}
    prop = {"type": page_type, page_type: ([{"plain_text": value}] if page_type == "rich_text"
                                        else [{"id": item} for item in value]), "has_more": False}
    page = {"properties": {"Name": {"type": "title", "title": [{"plain_text": "Review"}]},
                           "Fixed": {"type": "checkbox", "checkbox": True}, "Predecessors": prop}}

    def handler(request):
        return httpx.Response(200, json={"properties": schema} if "/data_sources/" in request.url.path else page)

    provider = _provider(tmp_path, monkeypatch, handler)
    config = provider.config
    if mode is not None:
        config["notion"]["predecessors_type"] = mode
    provider.config_path.write_text(json.dumps(config), encoding="utf-8")
    return LiveProvider(provider.config_path, client=provider.client)


def test_notion_rich_text_predecessors_require_explicit_opt_in(tmp_path, monkeypatch):
    provider = _predecessor_provider(tmp_path, monkeypatch, mode="rich_text")
    assert provider.read("notion:M1")["fields"]["Predecessors"] == ["T1", "M2"]
    provider = _predecessor_provider(tmp_path, monkeypatch)
    with pytest.raises(ProviderError, match="wrong type"):
        provider.read("notion:M1")


@pytest.mark.parametrize("value, message", [
    ("T1, T1", "duplicate"), ("M1", "itself"), ("T999", "unknown logical ID"),
    ("page-t1", "unknown logical ID"), ("T1,,M2", "empty logical ID"),
])
def test_notion_rich_text_rejects_invalid_predecessors(tmp_path, monkeypatch, value, message):
    provider = _predecessor_provider(tmp_path, monkeypatch, mode="rich_text", value=value)
    with pytest.raises(ProviderError, match=message):
        provider.read("notion:M1")


def test_notion_rich_text_allows_empty_predecessors(tmp_path, monkeypatch):
    provider = _predecessor_provider(tmp_path, monkeypatch, mode="rich_text", value="  ")
    assert provider.read("notion:M1")["fields"]["Predecessors"] == []


@pytest.mark.parametrize("schema_type,page_type", [("relation", "relation"), ("rich_text", "relation")])
def test_notion_rich_text_mode_checks_both_schema_and_page_types(tmp_path, monkeypatch, schema_type, page_type):
    provider = _predecessor_provider(tmp_path, monkeypatch, mode="rich_text",
                                     schema_type=schema_type, page_type=page_type, value=["page-t1"])
    with pytest.raises(ProviderError, match="wrong type"):
        provider.read("notion:M1")


def test_notion_invalid_predecessor_mode_is_rejected_in_configuration(tmp_path, monkeypatch):
    with pytest.raises(ProviderError, match="predecessors_type"):
        _predecessor_provider(tmp_path, monkeypatch, mode="auto")


@pytest.mark.parametrize("value,message", [
    (["unlisted-page"], "non-allowlisted page"), (["page-t1", "page-t1"], "duplicate"),
    (["page-m1"], "itself"),
])
def test_notion_relation_still_validates_allowlist_and_dependency_ids(tmp_path, monkeypatch, value, message):
    provider = _predecessor_provider(tmp_path, monkeypatch, schema_type="relation", value=value)
    with pytest.raises(ProviderError, match=message):
        provider.read("notion:M1")


def test_unknown_resource_and_fields_are_rejected_before_http(tmp_path, monkeypatch):
    calls = []
    provider = _provider(tmp_path, monkeypatch, lambda request: calls.append(request))
    with pytest.raises(ProviderError, match="Unknown record"):
        provider.read("github:T999")
    with pytest.raises(ProviderError, match="not writable"):
        provider.write("github:REL", {"title": "changed"})
    with pytest.raises(ProviderError, match="not writable"):
        provider.write("calendar:M2", {"description": "changed"}, etag='"v1"')
    assert calls == []


def test_github_uses_version_and_pages_all_issues(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        assert request.headers["X-GitHub-Api-Version"] == "2026-03-10"
        if request.url.path.endswith("/milestones/7"):
            return httpx.Response(
                200,
                json={
                    "number": 7,
                    "title": "Atlas",
                    "description": "release",
                    "due_on": "2026-09-25T00:00:00Z",
                    "html_url": "https://github.test/m/7",
                },
            )
        return httpx.Response(
            200,
            json={
                "number": 11,
                "title": "Requirements",
                "state": "closed",
                "milestone": {"number": 7},
                "html_url": "https://github.test/i/11",
            },
        )

    provider = _provider(tmp_path, monkeypatch, handler)
    record = provider.read("github:REL")
    assert record["fields"] == {"due_on": "2026-09-25T00:00:00Z", "title": "Atlas", "description": "release"}
    provider.write("github:REL", {"due_on": "2026-09-24T00:00:00Z"})
    assert json.loads(seen[-1].content) == {"due_on": "2026-09-24T00:00:00Z"}


def test_notion_current_version_preserves_extra_fields_and_maps_date(tmp_path, monkeypatch):
    seen = []
    page = {
        "id": "page-t1",
        "url": "https://notion.test/t1",
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "Requirements approved"}]},
            "Schedule": {"type": "date", "date": {"start": "2026-09-11", "end": None}},
            "EstimateDays": {"type": "number", "number": 1},
            "Fixed": {"type": "checkbox", "checkbox": True},
            "Status": {"type": "status", "status": {"name": "Done"}},
            "Predecessors": {"type": "relation", "relation": [], "has_more": False},
            "NotBefore": {"type": "date", "date": None},
            "Extra": {"type": "rich_text", "rich_text": [{"plain_text": "keep me"}]},
            "DeliveryDate": {"type": "date", "date": None},
            "AcceptedPlan": {"type": "rich_text", "rich_text": []},
        },
    }

    def handler(request):
        seen.append(request)
        assert request.headers["Notion-Version"] == "2026-03-11"
        if request.method == "GET" and "/data_sources/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": "ds-1",
                    "properties": {k: {"type": v["type"]} for k, v in page["properties"].items()},
                },
            )
        if request.method == "GET":
            return httpx.Response(200, json=page)
        return httpx.Response(200, json=page)

    provider = _provider(tmp_path, monkeypatch, handler)
    record = provider.read("notion:T1")
    assert record["fields"]["Schedule"] == {"start": "2026-09-11", "end": "2026-09-11"}
    assert record["fields"]["Extra"] == "keep me"
    provider.write("notion:T1", {"Schedule": {"start": "2026-09-12", "end": "2026-09-12"}})
    assert json.loads(seen[-1].content) == {
        "properties": {"Schedule": {"date": {"start": "2026-09-12", "end": "2026-09-12"}}}
    }


def test_calendar_if_match_timezone_all_day_and_recurring_read_only(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        if request.method == "GET" and len([item for item in seen if item.method == "GET"]) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "event-m2",
                    "etag": '"v1"',
                    "summary": "Sign-off",
                    "description": "keep",
                    "location": "Room",
                    "transparency": "opaque",
                    "recurringEventId": "series",
                    "start": {"date": "2026-09-25"},
                    "end": {"date": "2026-09-26"},
                    "htmlLink": "https://calendar.test/e",
                },
            )
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "event-m2",
                    "etag": '"v1"',
                    "summary": "Sign-off",
                    "start": {"dateTime": "2026-09-25T15:00:00+05:30"},
                    "end": {"dateTime": "2026-09-25T16:00:00+05:30"},
                },
            )
        return httpx.Response(412, json={"error": {"message": "Precondition Failed"}})

    provider = _provider(tmp_path, monkeypatch, handler)
    record = provider.read("calendar:M2")
    assert record["fields"]["start"] == "2026-09-25T00:00:00+05:30"
    assert record["fields"]["end"] == "2026-09-26T00:00:00+05:30"
    assert record["fields"]["all_day"] is True and record["fields"]["recurring"] is True
    with pytest.raises(ProviderError) as exc:
        provider.write(
            "calendar:M2",
            {"start": "2026-09-24T15:00:00+05:30", "end": "2026-09-24T16:00:00+05:30"},
            etag='"v1"',
        )
    assert exc.value.kind == "stale"
    assert seen[-1].headers["If-Match"] == '"v1"'
    assert json.loads(seen[-1].content) == {
        "start": {"dateTime": "2026-09-24T15:00:00+05:30", "timeZone": "Asia/Kolkata"},
        "end": {"dateTime": "2026-09-24T16:00:00+05:30", "timeZone": "Asia/Kolkata"},
    }


def test_calendar_recurrence_is_rejected_before_patch(tmp_path, monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "event-m2",
                "etag": '"v1"',
                "summary": "Recurring sign-off",
                "recurringEventId": "series",
                "start": {"dateTime": "2026-09-25T15:00:00+05:30"},
                "end": {"dateTime": "2026-09-25T16:00:00+05:30"},
            },
        )

    provider = _provider(tmp_path, monkeypatch, handler)
    with pytest.raises(ProviderError, match="read-only"):
        provider.write(
            "calendar:M2",
            {"start": "2026-09-24T15:00:00+05:30", "end": "2026-09-24T16:00:00+05:30"},
            etag='"v1"',
        )
    assert [request.method for request in seen] == ["GET"]


def test_calendar_list_paginates_busy_records(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if request.url.params.get("pageToken") == "next":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "busy-2",
                            "summary": "Busy 2",
                            "start": {"dateTime": "2026-09-20T10:00:00Z"},
                            "end": {"dateTime": "2026-09-20T11:00:00Z"},
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "busy-1",
                        "summary": "Busy 1",
                        "start": {"dateTime": "2026-09-19T10:00:00Z"},
                        "end": {"dateTime": "2026-09-19T11:00:00Z"},
                    }
                ],
                "nextPageToken": "next",
            },
        )

    provider = _provider(tmp_path, monkeypatch, handler)
    records = provider.calendar_busy_records()
    assert [r["resource_id"] for r in records] == ["busy-1", "busy-2"]
    assert len(calls) == 2
    assert "timeMax=2026-10-24T00%3A00%3A00%2B05%3A30" in calls[0]


def test_missing_credentials_are_honest_and_make_no_http_calls(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("NOTION_TOKEN", raising=False)
    monkeypatch.delenv("GOOGLE_TOKEN_PATH", raising=False)
    calls = []
    provider = LiveProvider(
        _config(tmp_path), client=httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r)))
    )
    assert {x["provider"]: x["status"] for x in provider.health()} == {
        "notion": "missing",
        "github": "missing",
        "calendar": "missing",
    }
    with pytest.raises(ProviderError) as exc:
        provider.read("github:REL")
    assert exc.value.kind == "auth" and calls == []


def test_http_errors_are_redacted(tmp_path, monkeypatch):
    provider = _provider(
        tmp_path, monkeypatch, lambda request: httpx.Response(401, text="token github-secret google-secret")
    )
    with pytest.raises(ProviderError) as exc:
        provider.read("github:REL")
    assert exc.value.kind == "auth"
    assert "secret" not in str(exc.value)


def test_notion_relation_paginates_and_maps_page_ids_to_logical_ids(tmp_path, monkeypatch):
    page = {
        "id": "page-t1",
        "url": "https://notion.test/t1",
        "properties": {
            "Name": {"id": "name", "type": "title", "title": [{"plain_text": "Task"}]},
            "Schedule": {"id": "schedule", "type": "date", "date": {"start": "2026-09-11"}},
            "EstimateDays": {"id": "estimate", "type": "number", "number": 2},
            "Fixed": {"id": "fixed", "type": "checkbox", "checkbox": False},
            "Status": {"id": "status", "type": "status", "status": {"name": "In progress"}},
            "Predecessors": {
                "id": "pred",
                "type": "relation",
                "relation": [{"id": "page-m1"}],
                "has_more": True,
            },
            "NotBefore": {"id": "nb", "type": "date", "date": {"start": "2026-09-14"}},
            "DeliveryDate": {"id": "delivery", "type": "date", "date": None},
            "AcceptedPlan": {"id": "plan", "type": "rich_text", "rich_text": []},
        },
    }

    def handler(request):
        if "/properties/pred" in request.url.path:
            if request.url.params.get("start_cursor") == "cursor-2":
                return httpx.Response(
                    200, json={"results": [{"relation": {"id": "page-m2"}}], "has_more": False}
                )
            return httpx.Response(
                200,
                json={
                    "results": [{"relation": {"id": "page-m1"}}],
                    "has_more": True,
                    "next_cursor": "cursor-2",
                },
            )
        if "/data_sources/" in request.url.path:
            return httpx.Response(
                200,
                json={"properties": {k: {"type": v["type"]} for k, v in page["properties"].items()}},
            )
        return httpx.Response(200, json=page)

    provider = _provider(tmp_path, monkeypatch, handler)
    assert provider.read("notion:T1")["fields"]["Predecessors"] == ["M1", "M2"]


def test_node_uses_fresh_notion_metadata_instead_of_config_defaults(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, lambda request: httpx.Response(500))
    records = {
        "notion:T1": {
            "name": "Fresh task",
            "fields": {
                "Name": "Fresh task",
                "Schedule": {"start": "2026-09-16", "end": "2026-09-17"},
                "EstimateDays": 2,
                "Fixed": False,
                "Status": "In progress",
                "Predecessors": ["M1"],
                "NotBefore": "2026-09-14",
            },
            "source_url": "n",
        },
        "calendar:M1": {
            "name": "Calendar title",
            "fields": {"start": "2026-09-21T11:00:00+05:30", "end": "2026-09-21T12:00:00+05:30"},
            "source_url": "c",
        },
        "notion:M1": {
            "name": "Fresh review",
            "fields": {"Name": "Fresh review", "Fixed": True, "Predecessors": ["T1"]},
            "source_url": "n2",
        },
    }
    task = provider._node("T1", provider.config["nodes"]["T1"], records)
    meeting = provider._node("M1", provider.config["nodes"]["M1"], records)
    assert task["duration_days"] == 2 and task["predecessors"] == ["M1"]
    assert meeting["name"] == "Fresh review"
    assert meeting["fixed"] is True and meeting["predecessors"] == ["T1"]


def test_health_marks_ready_only_after_readonly_probe(tmp_path, monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "api.notion.com":
            return httpx.Response(200, json={"id": "ds-1"})
        if request.url.host == "api.github.com":
            return httpx.Response(200, json={"full_name": "acme/atlas"})
        return httpx.Response(200, json={"id": "owned@example.test"})

    provider = _provider(tmp_path, monkeypatch, handler)
    assert {item["provider"]: item["status"] for item in provider.health()} == {
        "notion": "ready",
        "github": "ready",
        "calendar": "ready",
    }
    assert len(calls) == 3 and all(request.method == "GET" for request in calls)
    calendar_call = next(request for request in calls if request.url.host == "www.googleapis.com")
    assert calendar_call.url.raw_path.decode().endswith("/calendars/owned%40example.test/events/event-m1")


def test_notion_blocks_incomplete_page_and_wrong_schema_type(tmp_path, monkeypatch):
    properties = {
        "Name": {"type": "title"},
        "Schedule": {"type": "date"},
        "EstimateDays": {"type": "number"},
        "Fixed": {"type": "checkbox"},
        "Status": {"type": "status"},
        "Predecessors": {"type": "relation"},
        "NotBefore": {"type": "date"},
        "DeliveryDate": {"type": "date"},
        "AcceptedPlan": {"type": "rich_text"},
    }

    def incomplete_handler(request):
        if "/data_sources/" in request.url.path:
            return httpx.Response(200, json={"properties": properties})
        return httpx.Response(
            200, json={"id": "page-t1", "properties": {"Name": {"type": "title", "title": []}}}
        )

    provider = _provider(tmp_path, monkeypatch, incomplete_handler)
    with pytest.raises(ProviderError, match="missing required property"):
        provider.read("notion:T1")

    properties["Predecessors"] = {"type": "rich_text"}
    provider = _provider(tmp_path, monkeypatch, incomplete_handler)
    with pytest.raises(ProviderError, match="wrong type"):
        provider.read("notion:T1")


def test_node_blocks_missing_authoritative_metadata(tmp_path, monkeypatch):
    provider = _provider(tmp_path, monkeypatch, lambda request: httpx.Response(500))
    records = {
        "calendar:M1": {
            "name": "Review",
            "fields": {"start": "2026-09-21T11:00:00+05:30", "end": "2026-09-21T12:00:00+05:30"},
            "source_url": "c",
        },
        "notion:M1": {"name": "Review", "fields": {"Name": "Review"}, "source_url": "n"},
    }
    with pytest.raises(ProviderError, match="missing authoritative"):
        provider._node("M1", provider.config["nodes"]["M1"], records)
