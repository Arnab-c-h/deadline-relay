"""Approval-bound orchestration and read-before-retry recovery."""
import hashlib
import json
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from relay.intent import simulated_date
from relay.providers.base import ProviderError
from relay.scheduler import propose

RUNNING = {"QUEUED", "PREFLIGHT", "EXECUTING", "VERIFYING"}
UNFINISHED = RUNNING | {"PARTIAL", "UNCERTAIN", "FAILED"}


def now():
    return datetime.now(UTC).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan_hash(plan):
    return digest({key: value for key, value in plan.items() if key != "hash"})


class WorkflowError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class RelayService:
    def __init__(self, store, provider, mode="simulated"):
        self.store, self.provider, self.mode = store, provider, mode
        self.execution_guard = threading.Lock()

    def health(self):
        connections = self.provider.health()
        setup = [] if self.mode == "simulated" else [
            "Select an LLM provider/model and configure runtime access before live planning.",
            "Verify dedicated Notion, GitHub and Google Calendar resources.",
        ]
        return {"mode": self.mode, "project": {"name": "Atlas Release 1.0", "timezone": "Asia/Kolkata"},
                "connections": connections,
                "model": {"status": "simulated" if self.mode == "simulated" else "missing",
                          "detail": "Offline date parser; no LLM call" if self.mode == "simulated"
                          else "Live model configuration required"},
                "runs": [{key: run[key] for key in ("id", "status", "updated_at")} for run in self.store.runs()],
                "setup_required": setup}

    def snapshot(self):
        snapshot = self.provider.snapshot()
        snapshot.update(id=uuid4().hex, captured_at=now(), mode=self.mode)
        self.store.save("snapshots", snapshot["id"], snapshot)
        return snapshot

    def plan(self, snapshot_id, request, alternative_date=None, parent_plan_id=None):
        if self.mode == "live":
            raise WorkflowError("Live model access is not configured. Choose a provider/model before live planning.", 503)
        snapshot = self.store.get("snapshots", snapshot_id)
        if snapshot["mode"] != self.mode:
            raise WorkflowError("Snapshot belongs to another execution mode")
        if alternative_date:
            if not parent_plan_id:
                raise WorkflowError("Alternative requires the prior server-generated plan")
            parent = self.store.get("plans", parent_plan_id)
            if (parent["snapshot_id"] != snapshot_id or parent["status"] != "infeasible"
                    or parent["proposed_date"] != alternative_date or parent["request"] != request):
                raise WorkflowError("Alternative does not match the prior proposal")
            requested_date = alternative_date
        else:
            requested_date = simulated_date(request)
        if requested_date:
            result = propose(snapshot, requested_date)
        else:
            result = {"status": "clarification", "requested_date": None, "proposed_date": None,
                      "explanation": "Please enter one complete date, such as September 24, 2026 or 2026-09-24.",
                      "conflicts": [], "operations": [], "items": [], "assumptions": []}
        plan = {**result, "id": uuid4().hex, "version": 1, "snapshot_id": snapshot_id,
                "request": request, "created_at": now(), "mode": self.mode,
                "parent_plan_id": parent_plan_id,
                "interpretation": {"method": "simulated-date-parser", "model": None, "usage": None}}
        for op in plan["operations"]:
            if op["record_key"] == "notion:REL":
                op["before"]["AcceptedPlan"] = snapshot["records"]["notion:REL"]["fields"]["AcceptedPlan"]
                op["after"]["AcceptedPlan"] = f"{plan['id']}:v1"
        plan["hash"] = plan_hash(plan)
        self.store.save("plans", plan["id"], plan)
        return plan

    def approve(self, plan_id, version, supplied_hash, idempotency_key):
        plan = self.store.get("plans", plan_id)
        if plan["mode"] != self.mode or plan["status"] != "ready":
            raise WorkflowError("Only a ready plan from this mode can be approved")
        if version != plan["version"] or supplied_hash != plan["hash"] or plan_hash(plan) != supplied_hash:
            raise WorkflowError("Plan version or hash changed. Review the plan again.")
        payload = digest({"action": "approve", "plan_id": plan_id, "version": version, "hash": supplied_hash})
        with self.store.transaction() as db:
            existing_key = db.execute("SELECT * FROM requests WHERE key=?", (idempotency_key,)).fetchone()
            if existing_key:
                if existing_key["payload"] != payload:
                    raise WorkflowError("Idempotency key was used for a different request")
                return {"run_id": existing_key["run_id"]}
            existing = db.execute("SELECT id FROM runs WHERE plan_id=?", (plan_id,)).fetchone()
            if existing:
                db.execute("INSERT INTO requests VALUES(?,?,?)", (idempotency_key, payload, existing["id"]))
                return {"run_id": existing["id"]}
            active = db.execute("SELECT id,status FROM runs").fetchall()
            if any(row["status"] in UNFINISHED for row in active):
                raise WorkflowError("An unfinished run exists. Resume it before approving another plan.")
            run_id = uuid4().hex
            run = {"id": run_id, "plan_id": plan_id, "status": "QUEUED", "mode": self.mode,
                   "created_at": now(), "updated_at": now(), "reason": None,
                   "approval": {"version": version, "hash": supplied_hash, "approved_at": now(),
                                "operator": "local-owner"},
                   "operations": [{**deepcopy(op), "status": "PENDING", "attempts": 0,
                                   "evidence": None, "error": None} for op in plan["operations"]]}
            db.execute("INSERT INTO runs VALUES(?,?,?,?)", (run_id, plan_id, "QUEUED", json.dumps(run)))
            db.execute("INSERT INTO requests VALUES(?,?,?)", (idempotency_key, payload, run_id))
        return {"run_id": run_id}

    def run(self, run_id):
        return self.store.get_run(run_id)

    def _save(self, run, status=None, reason=None):
        run["updated_at"] = now()
        if status:
            run["status"] = status
        run["reason"] = reason
        self.store.save_run(run)

    def resume(self, run_id, idempotency_key):
        payload = digest({"action": "resume", "run_id": run_id})
        with self.store.transaction() as db:
            row = db.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            run = json.loads(row["data"])
            prior = db.execute("SELECT * FROM requests WHERE key=?", (idempotency_key,)).fetchone()
            if prior and prior["payload"] != payload:
                raise WorkflowError("Idempotency key was used for a different request")
            if run["status"] in {"STALE", "VERIFICATION_FAILED", "EXHAUSTED"}:
                raise WorkflowError("Source state needs review. Create a fresh snapshot and plan.")
            if run["mode"] != self.mode:
                raise WorkflowError("Run belongs to another execution mode")
            if not prior:
                db.execute("INSERT INTO requests VALUES(?,?,?)", (idempotency_key, payload, run_id))
        return {"run_id": run_id}

    def recovery_plan(self, run_id):
        """Prepare remaining edits after exhausted retries; still requires fresh approval."""
        run = self.run(run_id)
        if run["status"] != "EXHAUSTED":
            raise WorkflowError("A recovery plan is available only after the retry budget is exhausted")
        original = self.store.get("plans", run["plan_id"])
        baseline = self.store.get("snapshots", original["snapshot_id"])
        current = self.snapshot()
        expected = self._expected(baseline, run)
        drift = self._drift(current["records"], expected)
        if drift or current["config_hash"] != baseline["config_hash"]:
            raise WorkflowError(drift or "Project configuration changed")
        remaining = [deepcopy(op) for op in original["operations"]
                     if not self._matches(current["records"][op["record_key"]], op["after"])]
        projected = deepcopy(current)
        for op in remaining:
            projected["records"][op["record_key"]]["fields"].update(op["after"])
        for node in projected["nodes"]:
            fields = projected["records"][node["record_key"]]["fields"]
            if node["kind"] == "task":
                node.update(start=fields["Schedule"]["start"], end=fields["Schedule"]["end"])
            elif node["kind"] == "meeting":
                node.update(start=fields["start"], end=fields["end"])
            else:
                node.update(start=fields["DeliveryDate"], end=fields["DeliveryDate"])
        projected["project"]["deadline"] = projected["records"]["notion:REL"]["fields"]["DeliveryDate"]
        validation = propose(projected, original["proposed_date"])
        if validation["status"] != "ready" or validation["operations"]:
            raise WorkflowError("Remaining edits no longer produce a valid schedule. Review changed sources.")
        plan = {**deepcopy(original), "id": uuid4().hex, "version": original["version"] + 1,
                "snapshot_id": current["id"], "created_at": now(), "operations": remaining,
                "parent_plan_id": original["id"], "recovery_run_id": run_id,
                "explanation": "Recovery plan: approve only the unfinished edits. Previous verified changes are preserved."}
        for index, op in enumerate(remaining, start=1):
            op["id"] = f"op-{index}"
            op["before"] = {key: current["records"][op["record_key"]]["fields"].get(key) for key in op["after"]}
            if op["record_key"] == "notion:REL":
                op["after"]["AcceptedPlan"] = f"{plan['id']}:v{plan['version']}"
        current_nodes = {node["id"]: node for node in current["nodes"]}
        projected_nodes = {node["id"]: node for node in projected["nodes"]}
        for item in plan["items"]:
            node = current_nodes.get(item["id"])
            if node is None:
                continue
            target = projected_nodes[item["id"]]
            item["before"] = node["start"] if node["start"] == node["end"] else f"{node['start']} to {node['end']}"
            item["after"] = target["start"] if target["start"] == target["end"] else f"{target['start']} to {target['end']}"
            if item["disposition"] not in {"unrelated", "constraint"}:
                item["disposition"] = "changed" if item["before"] != item["after"] else "unchanged"
        plan["hash"] = plan_hash(plan)
        self.store.save("plans", plan["id"], plan)
        return plan

    @staticmethod
    def _matches(record, expected):
        return all(record["fields"].get(key) == value for key, value in expected.items())

    def _expected(self, snapshot, run):
        expected = deepcopy(snapshot["records"])
        for op in run["operations"]:
            if op["status"] == "VERIFIED":
                expected[op["record_key"]]["fields"].update(op["after"])
                if op.get("evidence"):
                    expected[op["record_key"]]["etag"] = op["evidence"].get("etag")
        return expected

    @staticmethod
    def _drift(current, expected):
        if set(current) != set(expected):
            return "Resource membership changed since the approved snapshot"
        for key, record in expected.items():
            actual = current[key]
            if actual["resource_id"] != record["resource_id"] or actual["fields"] != record["fields"]:
                return f"Source changed: {record['name']} ({key})"
            if key.startswith("calendar:") and actual.get("etag") != record.get("etag"):
                return f"Calendar version changed: {record['name']}"
        return None

    def _verified(self, run, op, record, reconciled=False):
        op.update(status="VERIFIED", error=None,
                  evidence={"verified_at": now(), "values": {key: record["fields"].get(key) for key in op["after"]},
                            "etag": record.get("etag"), "source_url": record.get("source_url"),
                            "reconciled": reconciled})
        self.store.attempt(run["id"], op["id"], {"event": "verified", **op["evidence"]})
        self._save(run)

    def execute(self, run_id):
        # One process and a non-blocking guard prevent concurrent local executors.
        if not self.execution_guard.acquire(blocking=False):
            return
        try:
            run = self.run(run_id)
            if run["status"] in {"VERIFIED", "STALE", "VERIFICATION_FAILED", "EXHAUSTED"}:
                return
            plan = self.store.get("plans", run["plan_id"])
            if plan_hash(plan) != run["approval"]["hash"] or plan["mode"] != self.mode:
                self._save(run, "STALE", "Approved plan no longer matches its persisted content")
                return
            snapshot = self.store.get("snapshots", plan["snapshot_id"])
            self._save(run, "PREFLIGHT")
            # Crash/timeout reconciliation happens before comparing expected partial state.
            for op in run["operations"]:
                if op["status"] in {"IN_FLIGHT", "UNCERTAIN", "APPLIED_UNVERIFIED"}:
                    record = self.provider.read(op["record_key"])
                    if self._matches(record, op["after"]):
                        self._verified(run, op, record, reconciled=True)
                    elif self._matches(record, op["before"]):
                        op["status"] = "PENDING"
                    else:
                        self._save(run, "STALE", f"Uncertain operation changed externally: {op['name']}")
                        return
            current = self.provider.snapshot()
            expected = self._expected(snapshot, run)
            drift = self._drift(current["records"], expected)
            if drift or current["config_hash"] != snapshot["config_hash"]:
                self._save(run, "STALE", drift or "Project configuration changed")
                return
            self._save(run, "EXECUTING")
            started = time.monotonic()
            for op in run["operations"]:
                if op["status"] == "VERIFIED":
                    continue
                if op["attempts"] >= 3:
                    self._save(run, "EXHAUSTED", "Retry budget exhausted. Review a recovery plan and approve the remaining edits.")
                    return
                while op["attempts"] < 3:
                    before = self.provider.read(op["record_key"])
                    changed_etag = (op["provider"] == "calendar"
                                    and before.get("etag") != expected[op["record_key"]].get("etag"))
                    if before["fields"] != expected[op["record_key"]]["fields"] or changed_etag:
                        self._save(run, "STALE", f"Source changed immediately before write: {op['name']}")
                        return
                    op.update(status="IN_FLIGHT", attempts=op["attempts"] + 1, error=None)
                    self._save(run)
                    self.store.attempt(run_id, op["id"], {"event": "intent", "attempt": op["attempts"],
                                                         "at": now(), "values": op["after"]})
                    error = None
                    try:
                        self.provider.write(op["record_key"], op["after"], before.get("etag"))
                        op["status"] = "APPLIED_UNVERIFIED"
                        self._save(run)
                    except ProviderError as exc:
                        error = exc
                        op.update(status="UNCERTAIN" if exc.kind in {"uncertain", "transient"} else "FAILED",
                                  error=str(exc))
                        self.store.attempt(run_id, op["id"], {"event": "provider_error", "kind": exc.kind,
                                                             "message": str(exc), "at": now()})
                        self._save(run)
                    try:
                        after = self.provider.read(op["record_key"])
                    except ProviderError:
                        op["status"] = "UNCERTAIN"
                        self._save(run, "UNCERTAIN", "Write outcome cannot be established. Resume checks state before retrying.")
                        return
                    if self._matches(after, op["after"]):
                        expected_record = deepcopy(before["fields"])
                        expected_record.update(op["after"])
                        if after["fields"] != expected_record:
                            op.update(status="FAILED", error="Unapproved fields changed during write")
                            self._save(run, "VERIFICATION_FAILED", op["error"])
                            return
                        self._verified(run, op, after, reconciled=error is not None)
                        expected[op["record_key"]] = after
                        break
                    if error is None:
                        op.update(status="FAILED", error="Provider read-back does not match approved values")
                        self._save(run, "VERIFICATION_FAILED", op["error"])
                        return
                    if not self._matches(after, op["before"]):
                        self._save(run, "STALE", f"Provider state differs from both before and after: {op['name']}")
                        return
                    if error.kind == "stale":
                        self._save(run, "STALE", "Provider rejected a stale conditional write. Review fresh sources.")
                        return
                    if error.kind not in {"transient", "uncertain"} or op["attempts"] >= 3:
                        status = "EXHAUSTED" if op["attempts"] >= 3 else (
                            "PARTIAL" if any(x["status"] == "VERIFIED" for x in run["operations"]) else "FAILED")
                        self._save(run, status, str(error))
                        return
                    delay = max(2 ** (op["attempts"] - 1), getattr(error, "retry_after", 0) or 0)
                    if time.monotonic() - started + delay > 120:
                        self._save(run, "PARTIAL", "Automatic retry time budget reached; resume after provider recovery")
                        return
                    time.sleep(delay)
            self._save(run, "VERIFYING")
            final = self.provider.snapshot()
            drift = self._drift(final["records"], expected)
            validation = propose(final, plan["proposed_date"])
            if drift or validation["status"] != "ready" or validation["operations"]:
                self._save(run, "VERIFICATION_FAILED", drift or "Resulting schedule failed constraint verification")
                return
            run["verification"] = {"checked_at": now(), "constraints_passed": True,
                                   "preservation_passed": True, "verified_operations": len(run["operations"]),
                                   "mode": self.mode, "note": "Observed state at verification time; not a future concurrency guarantee"}
            self._save(run, "VERIFIED")
        except ProviderError as exc:
            run = self.run(run_id)
            uncertain = any(op["status"] in {"IN_FLIGHT", "UNCERTAIN", "APPLIED_UNVERIFIED"} for op in run["operations"])
            self._save(run, "UNCERTAIN" if uncertain else "PARTIAL", str(exc))
        except Exception:
            # Persist an honest pause without disclosing raw transport/configuration errors.
            run = self.run(run_id)
            for op in run["operations"]:
                if op["status"] in {"IN_FLIGHT", "APPLIED_UNVERIFIED"}:
                    op["status"] = "UNCERTAIN"
            self._save(run, "UNCERTAIN", "Execution interrupted. Inspect local logs and resume to reconcile provider state.")
            raise
        finally:
            self.execution_guard.release()

    def reset(self):
        if self.mode != "simulated":
            raise WorkflowError("Reset is only available for simulated resources", 403)
        if not self.execution_guard.acquire(blocking=False):
            raise WorkflowError("An execution is active")
        try:
            with self.store.transaction() as db:
                statuses = db.execute("SELECT status FROM runs").fetchall()
                if any(row["status"] in UNFINISHED for row in statuses):
                    raise WorkflowError("An unfinished run exists; reset would erase recovery evidence")
                db.execute("DELETE FROM records")
                # Keep plan/run evidence; reset creates a new fixture generation/config hash below.
            from relay.simulation import SimulationProvider
            self.provider = SimulationProvider(self.store)
            self.store.save("meta", "generation", {"id": uuid4().hex})
        finally:
            self.execution_guard.release()
        return {"ok": True}
