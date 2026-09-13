"""Exercise the real app's guardrails after the reviewed acceptance plan completed.

Calls the configured real model. Replays an already completed approval and submits
a plan against the original stale snapshot; it does not reset or reseed providers.
"""
import json
import time
from pathlib import Path

import httpx


def main():
    root = Path('data')
    plan = json.loads((root / 'acceptance-plan.json').read_text())
    run = json.loads((root / 'acceptance-run.json').read_text())
    checks = json.loads((root / 'acceptance-checks.json').read_text())
    model_plans = []

    def record(case, **evidence):
        result = {'case': case, 'passed': True, **evidence}
        checks.append(result)
        (root / 'acceptance-checks.json').write_text(json.dumps(checks, indent=2))
        print(json.dumps(result), flush=True)

    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=180) as client:
        payload = {'version': plan['version'], 'hash': plan['hash'],
                   'idempotency_key': 'live-acceptance-duplicate'}
        for _ in range(2):
            response = client.post(f'/api/plans/{plan["id"]}/approve', json=payload)
            assert response.status_code == 202 and response.json()['run_id'] == run['id']
        record('duplicate_approval', same_run_id=run['id'])

        snapshot_response = client.post('/api/projects/demo/snapshots')
        snapshot_response.raise_for_status()
        snapshot = snapshot_response.json()
        (root / 'acceptance-final-snapshot.json').write_text(json.dumps(snapshot, indent=2))
        cases = [
            ('ambiguous_request', 'Move the release deadline to next Friday.', 'clarification'),
            ('unsupported_action', 'Move the release deadline to September 24, 2026 and email the whole team.',
             'unsupported'),
            ('already_applied_date', 'Move the release deadline to September 24, 2026.', 'ready'),
        ]
        for label, request, expected in cases:
            response = client.post('/api/projects/demo/plans', json={
                'snapshot_id': snapshot['id'], 'request': request})
            response.raise_for_status()
            result = response.json()
            model_plans.append(result)
            (root / 'acceptance-model-plans.json').write_text(json.dumps(model_plans, indent=2))
            assert result['status'] == expected and result['operations'] == [], (label, result['status'])
            record(label, status=result['status'], operations=0)

        # The first successful run changed the real apps. A new plan based on its
        # old snapshot must now be blocked without any provider writes.
        response = client.post('/api/projects/demo/plans', json={
            'snapshot_id': plan['snapshot_id'], 'request': plan['request'],
            'alternative_date': plan['proposed_date'], 'parent_plan_id': plan['parent_plan_id']})
        response.raise_for_status()
        stale = response.json()
        (root / 'acceptance-stale-plan.json').write_text(json.dumps(stale, indent=2))
        response = client.post(f'/api/plans/{stale["id"]}/approve', json={
            'version': stale['version'], 'hash': stale['hash'],
            'idempotency_key': 'live-acceptance-stale-' + stale['id']})
        response.raise_for_status()
        stale_run_id = response.json()['run_id']
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            stale_run = client.get('/api/runs/' + stale_run_id).json()
            if stale_run['status'] not in {'QUEUED', 'PREFLIGHT', 'EXECUTING', 'VERIFYING'}:
                break
            time.sleep(2)
        (root / 'acceptance-stale-run.json').write_text(json.dumps(stale_run, indent=2))
        assert stale_run['status'] == 'STALE'
        assert all(op['attempts'] == 0 for op in stale_run['operations'])
        record('stale_plan', status=stale_run['status'], write_attempts=0, reason=stale_run['reason'])
        repeated = client.get('/api/runs/' + run['id']).json()
        assert repeated['status'] == 'VERIFIED'
        assert all(op['attempts'] == 1 for op in repeated['operations'])
        record('completed_run_not_reexecuted', operation_attempts=[op['attempts'] for op in repeated['operations']])


if __name__ == '__main__':
    main()
