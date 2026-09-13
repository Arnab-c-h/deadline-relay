from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from .base import Provider, ProviderError, Record, Snapshot

NOTION_VERSION = "2026-03-11"
GITHUB_VERSION = "2026-03-10"
GOOGLE_SCOPES = {
    "https://www.googleapis.com/auth/calendar.events.owned",
    "https://www.googleapis.com/auth/calendar.freebusy",
}


class LiveProvider(Provider):
    """Direct API adapter configured solely from an explicit JSON mapping and runtime credentials."""

    def __init__(self, config_path: Path | str, *, client: httpx.Client | None = None):
        self.config_path = Path(config_path)
        try:
            raw = self.config_path.read_bytes()
            self.config = json.loads(raw)
        except (OSError, ValueError) as exc:
            raise ProviderError("Live provider configuration is missing or invalid") from exc
        self._validate_config()
        self.config_hash = hashlib.sha256(raw).hexdigest()
        self.client = client or httpx.Client(timeout=20)
        self._google_token_path = os.getenv("GOOGLE_TOKEN_PATH", "")
        self._credentials = {
            "github": os.getenv("GITHUB_TOKEN", "").strip(),
            "notion": os.getenv("NOTION_TOKEN", "").strip(),
            "calendar": self._load_google_token(self._google_token_path),
        }

    def _validate_config(self) -> None:
        required = {
            "project": ("id", "name", "timezone", "planning_start", "horizon_days", "deadline"),
            "notion": ("data_source_id", "properties", "records"),
            "github": ("owner", "repo", "milestone_number", "issues"),
            "calendar": ("calendar_id", "events"),
        }
        for section, fields in required.items():
            value = self.config.get(section)
            if not isinstance(value, dict):
                raise ProviderError(f"Missing configuration section: {section}")
            for field in fields:
                if value.get(field) in (None, ""):
                    raise ProviderError(f"Missing configuration value: {section}.{field}")
        if self.config["project"]["id"] != "demo":
            raise ProviderError("Only the demo project is allowed")
        required_properties = {
            "name",
            "schedule",
            "estimate_days",
            "fixed",
            "status",
            "predecessors",
            "not_before",
            "delivery_date",
            "accepted_plan",
        }
        if not required_properties.issubset(self.config["notion"]["properties"]):
            raise ProviderError("Notion property mapping is incomplete")
        if self.config["notion"].get("predecessors_type", "relation") not in ("relation", "rich_text"):
            raise ProviderError("notion.predecessors_type must be relation or rich_text")
        for provider, mapping_name in (("notion", "records"), ("github", "issues"), ("calendar", "events")):
            mapping = self.config[provider][mapping_name]
            if not isinstance(mapping, dict) or any(value in (None, "") for value in mapping.values()):
                raise ProviderError(f"{provider.title()} resource mapping contains a blank ID")
        for logical, spec in self.config.get("nodes", {}).items():
            if not isinstance(spec, dict) or "record_key" not in spec:
                raise ProviderError(f"Node mapping is invalid: {logical}")
            self._resolve(spec["record_key"])
            if spec.get("metadata_record_key"):
                self._resolve(spec["metadata_record_key"])

    @staticmethod
    def _load_google_token(path_value: str) -> str:
        if not path_value:
            return ""
        path = Path(path_value)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        # Refresh, when needed, remains within Google's installed-app credential flow.
        if data.get("token") and not data.get("refresh_token"):
            return str(data["token"])
        try:
            from google.auth.exceptions import GoogleAuthError
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials

            credentials = Credentials.from_authorized_user_info(data)
            if credentials.scopes and not GOOGLE_SCOPES.issubset(credentials.scopes):
                return ""
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                path.write_text(credentials.to_json(), encoding="utf-8")
            return credentials.token or ""
        except (GoogleAuthError, OSError, ValueError):
            return ""

    def health(self) -> list[dict[str, str]]:
        result = []
        for provider in ("notion", "github", "calendar"):
            if not self._credential(provider):
                result.append(
                    {"provider": provider, "status": "missing", "detail": "runtime credential missing"}
                )
                continue
            try:
                if provider == "notion":
                    url = self._notion_url(f"data_sources/{self.config['notion']['data_source_id']}")
                elif provider == "github":
                    url = self._github_url("")
                else:
                    url = self._calendar_url(str(self.config["calendar"]["events"]["M1"]))
                self._request(provider, "GET", url)
                result.append({"provider": provider, "status": "ready", "detail": "read access verified"})
            except ProviderError as exc:
                result.append(
                    {"provider": provider, "status": "error", "detail": f"read probe failed ({exc.kind})"}
                )
        return result

    def _credential(self, provider: str) -> str:
        if provider == "calendar" and self._google_token_path:
            self._credentials["calendar"] = self._load_google_token(self._google_token_path)
        return self._credentials[provider]

    def _require_auth(self, provider: str) -> str:
        token = self._credential(provider)
        if not token:
            raise ProviderError(f"{provider.title()} runtime credential is missing", kind="auth")
        return token

    def _request(self, provider: str, method: str, url: str, **kwargs: Any) -> httpx.Response:
        token = self._require_auth(provider)
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        if provider == "notion":
            headers["Notion-Version"] = NOTION_VERSION
            headers.setdefault("Content-Type", "application/json")
        elif provider == "github":
            headers["Accept"] = "application/vnd.github+json"
            headers["X-GitHub-Api-Version"] = GITHUB_VERSION
        try:
            response = self.client.request(method, url, headers=headers, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            kind = "uncertain" if method not in {"GET", "HEAD"} else "transient"
            raise ProviderError(f"{provider.title()} request failed", kind=kind) from exc
        if response.is_success:
            return response
        kind = (
            "stale"
            if response.status_code == 412
            else "auth"
            if response.status_code in (401, 403)
            else "transient"
            if response.status_code == 429 or response.status_code >= 500
            else "permanent"
        )
        retry_after = float(response.headers.get("Retry-After", 0) or 0)
        raise ProviderError(
            f"{provider.title()} request failed with HTTP {response.status_code}",
            kind=kind,
            retry_after=retry_after,
        )

    def _resolve(self, record_key: str) -> tuple[str, str | int]:
        if ":" not in record_key:
            raise ProviderError(f"Unknown record: {record_key}")
        provider, logical = record_key.split(":", 1)
        resource: str | int | None = None
        if provider == "notion":
            resource = self.config["notion"]["records"].get(logical)
        elif provider == "calendar":
            resource = self.config["calendar"]["events"].get(logical)
        elif provider == "github":
            resource = (
                self.config["github"]["milestone_number"]
                if logical == "REL"
                else self.config["github"]["issues"].get(logical)
            )
        if resource in (None, ""):
            raise ProviderError(f"Unknown record: {record_key}")
        return provider, resource

    def read(self, record_key: str) -> Record:
        provider, resource = self._resolve(record_key)
        if provider == "notion":
            return self._read_notion(record_key, str(resource))
        if provider == "github":
            return self._read_github(record_key, int(resource))
        return self._read_calendar(record_key, str(resource))

    def write(self, record_key: str, changes: dict[str, Any], etag: str | None = None) -> None:
        provider, resource = self._resolve(record_key)
        logical = record_key.split(":", 1)[1]
        allowed = {
            "notion": {"DeliveryDate", "AcceptedPlan"} if logical == "REL" else {"Schedule"},
            "github": {"due_on"} if logical == "REL" else set(),
            "calendar": {"start", "end"} if logical == "M2" else set(),
        }[provider]
        if not changes or not set(changes).issubset(allowed):
            raise ProviderError(f"One or more fields are not writable for {record_key}")
        if provider == "notion":
            self._write_notion(logical, str(resource), changes)
        elif provider == "github":
            self._request("github", "PATCH", self._github_url(f"milestones/{resource}"), json=changes)
        else:
            if set(changes) != {"start", "end"} or not etag:
                raise ProviderError("Calendar start/end updates require both fields and an ETag")
            current = self._read_calendar(record_key, str(resource))
            if current["fields"]["recurring"] or current["fields"]["all_day"]:
                raise ProviderError("Recurring and all-day Calendar events are read-only")
            body = {
                key: {"dateTime": changes[key], "timeZone": self.config["project"]["timezone"]}
                for key in ("start", "end")
            }
            self._request(
                "calendar", "PATCH", self._calendar_url(str(resource)), headers={"If-Match": etag}, json=body
            )

    def _notion_url(self, path: str) -> str:
        return f"https://api.notion.com/v1/{path}"

    def _github_url(self, path: str) -> str:
        cfg = self.config["github"]
        return f"https://api.github.com/repos/{quote(cfg['owner'])}/{quote(cfg['repo'])}/{path}"

    def _calendar_url(self, event_id: str | None = None) -> str:
        cid = quote(self.config["calendar"]["calendar_id"], safe="")
        base = f"https://www.googleapis.com/calendar/v3/calendars/{cid}/events"
        return f"{base}/{quote(event_id, safe='')}" if event_id else base

    def _read_notion(self, key: str, page_id: str) -> Record:
        schema = (
            self._request(
                "notion", "GET", self._notion_url(f"data_sources/{self.config['notion']['data_source_id']}")
            )
            .json()
            .get("properties", {})
        )
        configured = self.config["notion"]["properties"]
        expected_types = {
            "name": "title",
            "schedule": "date",
            "estimate_days": "number",
            "fixed": "checkbox",
            "status": "status",
            "predecessors": self.config["notion"].get("predecessors_type", "relation"),
            "not_before": "date",
            "delivery_date": "date",
            "accepted_plan": "rich_text",
        }
        for alias, name in configured.items():
            if name not in schema:
                raise ProviderError(f"Configured Notion property is absent: {alias}")
            if schema[name].get("type") != expected_types[alias]:
                raise ProviderError(f"Configured Notion property has wrong type: {alias}")
        page = self._request("notion", "GET", self._notion_url(f"pages/{page_id}")).json()
        logical = key.split(":", 1)[1]
        required_aliases = (
            {"name", "fixed", "predecessors"}
            if logical in {"M1", "M2"}
            else {"name", "delivery_date", "accepted_plan", "fixed", "predecessors"}
            if logical == "REL"
            else {"name", "schedule", "estimate_days", "fixed", "status", "predecessors", "not_before"}
        )
        page_properties = page.get("properties", {})
        for alias in required_aliases:
            name = configured[alias]
            if name not in page_properties:
                raise ProviderError(f"Notion page is missing required property: {alias}")
            if page_properties[name].get("type") != expected_types[alias]:
                raise ProviderError(f"Notion page property has wrong type: {alias}")
        raw_fields = {}
        for name, value in page_properties.items():
            if value.get("type") == "relation" and value.get("has_more"):
                raw_fields[name] = self._read_notion_relation(page_id, value.get("id", ""))
            else:
                raw_fields[name] = self._notion_value(value)
        canonical_names = {
            "name": "Name",
            "schedule": "Schedule",
            "estimate_days": "EstimateDays",
            "fixed": "Fixed",
            "status": "Status",
            "predecessors": "Predecessors",
            "not_before": "NotBefore",
            "delivery_date": "DeliveryDate",
            "accepted_plan": "AcceptedPlan",
        }
        fields = dict(raw_fields)
        for alias, canonical in canonical_names.items():
            property_name = configured[alias]
            if property_name in raw_fields:
                fields[canonical] = raw_fields[property_name]
                if property_name != canonical:
                    fields.pop(property_name, None)
        for scalar_date in ("NotBefore", "DeliveryDate"):
            if isinstance(fields.get(scalar_date), dict):
                fields[scalar_date] = fields[scalar_date]["start"]
        fields["Predecessors"] = self._notion_predecessors(logical, fields.get("Predecessors"))
        return {
            "key": key,
            "provider": "notion",
            "resource_id": page_id,
            "name": str(fields.get("Name", key)),
            "source_url": page.get("url"),
            "fields": fields,
            "etag": None,
        }

    def _notion_predecessors(self, logical: str, value: Any) -> list[str]:
        mode = self.config["notion"].get("predecessors_type", "relation")
        if mode == "rich_text":
            if not isinstance(value, str):
                raise ProviderError("Notion predecessor rich_text value must be text")
            predecessors = [item.strip() for item in value.split(",")] if value.strip() else []
            if any(not item for item in predecessors):
                raise ProviderError("Notion predecessors contain an empty logical ID")
        else:
            if not isinstance(value, list):
                raise ProviderError("Notion predecessor relation value must be a list")
            reverse_ids = {
                str(notion_page_id): node_id
                for node_id, notion_page_id in self.config["notion"]["records"].items()
            }
            try:
                predecessors = [reverse_ids[str(notion_page_id)] for notion_page_id in value]
            except KeyError as exc:
                raise ProviderError("Notion predecessor relation targets a non-allowlisted page") from exc
        allowed = set(self.config["notion"]["records"]) & set(self.config.get("nodes", {}))
        if any(item not in allowed for item in predecessors):
            raise ProviderError("Notion predecessor references an unknown logical ID")
        if len(predecessors) != len(set(predecessors)):
            raise ProviderError("Notion predecessors contain a duplicate logical ID")
        if logical in predecessors:
            raise ProviderError("Notion record cannot list itself as a predecessor")
        return predecessors

    def _read_notion_relation(self, page_id: str, property_id: str) -> list[str]:
        if not property_id:
            raise ProviderError("Paginated Notion relation has no property ID")
        values: list[str] = []
        cursor = None
        while True:
            params = {"start_cursor": cursor} if cursor else None
            payload = self._request(
                "notion",
                "GET",
                self._notion_url(f"pages/{page_id}/properties/{quote(property_id, safe='')}"),
                params=params,
            ).json()
            values.extend(
                item["relation"]["id"]
                for item in payload.get("results", [])
                if isinstance(item.get("relation"), dict) and item["relation"].get("id")
            )
            if not payload.get("has_more"):
                return values
            cursor = payload.get("next_cursor")
            if not cursor:
                raise ProviderError("Notion relation pagination is incomplete")

    @staticmethod
    def _notion_value(prop: dict[str, Any]) -> Any:
        typ = prop.get("type")
        value = prop.get(typ) if typ else None
        if typ in {"title", "rich_text"}:
            return "".join(str(item.get("plain_text", "")) for item in (value or []))
        if typ in {"status", "select"}:
            return value.get("name") if value else None
        if typ == "multi_select":
            return [item.get("name") for item in (value or [])]
        if typ == "relation":
            return [item.get("id") for item in (value or [])]
        if typ == "date" and value:
            return {"start": value["start"], "end": value.get("end") or value["start"]}
        return value

    def _write_notion(self, logical: str, page_id: str, changes: dict[str, Any]) -> None:
        properties = self.config["notion"]["properties"]
        body: dict[str, Any] = {"properties": {}}
        for field, value in changes.items():
            name = properties[
                "schedule"
                if field == "Schedule"
                else "delivery_date"
                if field == "DeliveryDate"
                else "accepted_plan"
            ]
            if field in {"Schedule", "DeliveryDate"}:
                date_value = value if isinstance(value, dict) else {"start": value}
                body["properties"][name] = {
                    "date": {"start": date_value["start"], "end": date_value.get("end")}
                }
            else:
                body["properties"][name] = {"rich_text": [{"text": {"content": str(value)}}]}
        self._request("notion", "PATCH", self._notion_url(f"pages/{page_id}"), json=body)

    def _read_github(self, key: str, number: int) -> Record:
        logical = key.split(":", 1)[1]
        obj = self._request(
            "github",
            "GET",
            self._github_url(f"milestones/{number}" if logical == "REL" else f"issues/{number}"),
        ).json()
        if logical == "REL":
            fields = {name: obj.get(name) for name in ("due_on", "title", "description")}
        else:
            fields = {
                "state": obj.get("state"),
                "milestone": (obj.get("milestone") or {}).get("number"),
                "title": obj.get("title"),
            }
        return {
            "key": key,
            "provider": "github",
            "resource_id": number,
            "name": obj.get("title", key),
            "source_url": obj.get("html_url"),
            "fields": fields,
            "etag": obj.get("etag"),
        }

    def _read_calendar(self, key: str, event_id: str) -> Record:
        event = self._request("calendar", "GET", self._calendar_url(event_id)).json()
        return self._calendar_record(key, event)

    def _calendar_record(self, key: str, event: dict[str, Any]) -> Record:
        tz = ZoneInfo(self.config["project"]["timezone"])
        start, start_all_day = self._calendar_time(event.get("start", {}), tz)
        end, end_all_day = self._calendar_time(event.get("end", {}), tz)
        fields = {
            "start": start,
            "end": end,
            "summary": event.get("summary", ""),
            "description": event.get("description", ""),
            "location": event.get("location", ""),
            "transparency": event.get("transparency", "opaque"),
            "recurring": bool(event.get("recurringEventId") or event.get("recurrence")),
            "all_day": start_all_day or end_all_day,
            "fixed": key != "calendar:M2",
        }
        return {
            "key": key,
            "provider": "calendar",
            "resource_id": event.get("id"),
            "name": fields["summary"],
            "source_url": event.get("htmlLink"),
            "fields": fields,
            "etag": event.get("etag"),
        }

    @staticmethod
    def _calendar_time(value: dict[str, Any], tz: ZoneInfo) -> tuple[str, bool]:
        if "date" in value:
            dt = datetime.combine(date.fromisoformat(value["date"]), time.min, tzinfo=tz)
            return dt.isoformat(), True
        raw = value.get("dateTime")
        if not raw:
            raise ProviderError("Calendar event has no start/end value")
        dt = datetime.fromisoformat(raw).astimezone(tz)
        return dt.isoformat(), False

    def calendar_busy_records(self) -> list[Record]:
        project = self.config["project"]
        start = datetime.combine(
            date.fromisoformat(project["planning_start"]), time.min, tzinfo=ZoneInfo(project["timezone"])
        )
        end = start
        working_days = 0
        while working_days < int(project["horizon_days"]):
            if end.weekday() < 5:
                working_days += 1
            end += timedelta(days=1)
        params: dict[str, Any] = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "singleEvents": "true",
            "maxResults": 2500,
        }
        records: list[Record] = []
        token = None
        allowlisted = set(self.config["calendar"]["events"].values())
        while True:
            if token:
                params["pageToken"] = token
            payload = self._request("calendar", "GET", self._calendar_url(), params=params).json()
            for event in payload.get("items", []):
                if event.get("id") not in allowlisted:
                    records.append(self._calendar_record(f"calendar:busy:{event.get('id')}", event))
            token = payload.get("nextPageToken")
            if not token:
                return records

    def snapshot(self) -> Snapshot:
        records: dict[str, Record] = {}
        for provider, config_name in (("notion", "records"), ("calendar", "events"), ("github", "issues")):
            for logical in self.config[provider][config_name]:
                key = f"{provider}:{logical}"
                records[key] = self.read(key)
        records["github:REL"] = self.read("github:REL")
        for busy in self.calendar_busy_records():
            records[busy["key"]] = busy
        nodes = [self._node(logical, spec, records) for logical, spec in self.config.get("nodes", {}).items()]
        return {
            "captured_at": datetime.now(UTC).isoformat(),
            "mode": "live",
            "project": deepcopy(self.config["project"]),
            "nodes": nodes,
            "records": records,
            "config_hash": self.config_hash,
        }

    def _node(self, logical: str, spec: dict[str, Any], records: dict[str, Record]) -> dict[str, Any]:
        record = records[spec["record_key"]]
        metadata = records.get(spec.get("metadata_record_key", spec["record_key"]), record)
        fields = record["fields"]
        metadata_fields = metadata["fields"]
        kind = spec["kind"]
        required_metadata = {"Name", "Fixed", "Predecessors"}
        if kind == "task":
            required_metadata |= {"Schedule", "EstimateDays", "Status", "NotBefore"}
        elif kind == "release":
            required_metadata |= {"DeliveryDate"}
        missing = required_metadata - metadata_fields.keys()
        if missing:
            raise ProviderError(
                f"Node {logical} is missing authoritative metadata: {', '.join(sorted(missing))}"
            )
        if kind == "task":
            schedule = fields["Schedule"]
            start, end = schedule["start"], schedule["end"]
        elif kind == "meeting":
            start, end = fields["start"], fields["end"]
        else:
            start = end = fields["DeliveryDate"]
        issue = records.get(spec.get("issue_record_key", ""), {}).get("fields", {})
        return {
            "id": logical,
            "name": metadata_fields.get("Name", metadata.get("name", record["name"])),
            "kind": kind,
            "record_key": spec["record_key"],
            "predecessors": list(metadata_fields.get("Predecessors", [])),
            "start": start,
            "end": end,
            "duration_days": metadata_fields.get("EstimateDays") if kind == "task" else None,
            "fixed": bool(metadata_fields.get("Fixed", False)),
            "completed": metadata_fields.get("Status") in {"Done", "Complete", "Completed"},
            "not_before": metadata_fields.get("NotBefore"),
            "issue_state": issue.get("state"),
            "source_url": record.get("source_url"),
        }
