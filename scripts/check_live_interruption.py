"""Prepare a real two-write test and stop only the explicitly supplied local server PID.

Run only against the dedicated September 2026 acceptance fixture.
The parent operator must verify the PID identifies this repository's uvicorn server.
"""
import argparse
import json
import os
import signal
import time
from pathlib import Path

import httpx

from relay.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-pid', type=int, required=True)
    parser.add_argument('--target-date', choices=['2026-09-24', '2026-09-25'], default='2026-09-25')
    parser.add_argument('--label', choices=['interruption', 'restoration'], default='interruption')
    args = parser.parse_args()
    root = Path('data')
    store = Store(root / 'relay-live.sqlite')
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=90) as client:
        response = client.post('/api/projects/demo/snapshots')
        response.raise_for_status()
        snapshot = response.json()
        response = client.post('/api/projects/demo/plans', json={
            'snapshot_id': snapshot['id'], 'request': f'Move the release deadline to {args.target_date}.'})
        response.raise_for_status()
        plan = response.json()
        assert plan['status'] == 'ready'
        assert {op['record_key'] for op in plan['operations']} == {'github:REL', 'notion:REL'}
        (root / f'acceptance-{args.label}-plan.json').write_text(json.dumps(plan, indent=2))
        response = client.post(f'/api/plans/{plan["id"]}/approve', json={
            'version': plan['version'], 'hash': plan['hash'], 'idempotency_key': 'interruption-' + plan['id']})
        response.raise_for_status()
        run_id = response.json()['run_id']
    print(json.dumps({'run_id': run_id, 'waiting_for': 'first persisted write intent'}), flush=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        run = store.get_run(run_id)
        if any(op['attempts'] for op in run['operations']):
            assert run['status'] in {'EXECUTING', 'VERIFYING'}, run['status']
            (root / f'acceptance-{args.label}-before-stop.json').write_text(json.dumps(run, indent=2))
            os.kill(args.server_pid, signal.SIGTERM)
            print(json.dumps({'server_stopped': args.server_pid, 'run_id': run_id,
                              'operations': [{k: op[k] for k in ('record_key', 'status', 'attempts')}
                                             for op in run['operations']]}), flush=True)
            return
        assert run['status'] in {'QUEUED', 'PREFLIGHT', 'EXECUTING'}, run['status']
        time.sleep(0.05)
    raise TimeoutError('No write intent observed; server was not stopped')


if __name__ == '__main__':
    main()
