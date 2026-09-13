"""Explicit persistent simulator; never selected as a fallback from live mode."""
import hashlib
from copy import deepcopy
from uuid import uuid4

from relay.fixtures import build_fixture
from relay.providers.base import ProviderError


class SimulationProvider:
    def __init__(self, store):
        self.store = store
        try:
            self.store.get("meta", "generation")
        except KeyError:
            self.store.save("meta", "generation", {"id": uuid4().hex})
        if not store.records():
            for record in build_fixture()["records"].values():
                store.put_record(record)

    def health(self):
        return [{"provider": name, "status": "simulated", "detail": "Local fictional records; no external API calls"}
                for name in ("notion", "github", "calendar")]

    def snapshot(self):
        snapshot = build_fixture()
        generation = self.store.get("meta", "generation")["id"]
        snapshot["config_hash"] = hashlib.sha256(f"{snapshot['config_hash']}:{generation}".encode()).hexdigest()
        snapshot["records"] = self.store.records()
        records = snapshot["records"]
        snapshot["project"]["deadline"] = records["notion:REL"]["fields"]["DeliveryDate"]
        for node in snapshot["nodes"]:
            fields = records[node["record_key"]]["fields"]
            if node["kind"] == "task":
                node.update(start=fields["Schedule"]["start"], end=fields["Schedule"]["end"],
                            duration_days=fields.get("EstimateDays"), fixed=fields["Fixed"],
                            completed=fields["Status"] == "Done", predecessors=fields["Predecessors"],
                            not_before=fields.get("NotBefore"))
                issue = records.get(f"github:{node['id']}")
                if issue:
                    node["issue_state"] = issue["fields"]["state"]
            elif node["kind"] == "meeting":
                node.update(start=fields["start"], end=fields["end"], fixed=fields.get("fixed", node["fixed"]))
            elif node["kind"] == "release":
                node.update(start=fields["DeliveryDate"], end=fields["DeliveryDate"])
        return snapshot

    def read(self, record_key):
        record = self.store.records().get(record_key)
        if record is None:
            raise ProviderError("Resource is not allowlisted")
        return deepcopy(record)

    def write(self, record_key, changes, etag=None):
        allowed = {
            "calendar:M2": {"start", "end"}, "notion:REL": {"DeliveryDate", "AcceptedPlan"},
            "github:REL": {"due_on"},
            **{f"notion:T{i}": {"Schedule"} for i in range(2, 6)},
        }
        if not changes or record_key not in allowed or not set(changes) <= allowed[record_key]:
            raise ProviderError("Write is outside the allowlisted fields")
        record = self.read(record_key)
        if record_key.startswith("calendar:") and (etag is None or record["etag"] != etag):
            raise ProviderError("Calendar resource changed", kind="stale")
        record["fields"].update(deepcopy(changes))
        record["etag"] = f'"{uuid4().hex}"'
        self.store.put_record(record)
