"""Read the allowlisted test resources directly; save raw evidence only under ignored data/."""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from relay.providers.live import LiveProvider


def capture():
    load_dotenv('.env', override=True)
    provider = LiveProvider('config.local.json')
    records = {}
    try:
        for logical, resource in provider.config['notion']['records'].items():
            records['notion:' + logical] = provider._request(
                'notion', 'GET', provider._notion_url('pages/' + resource)).json()
        for logical, resource in provider.config['github']['issues'].items():
            records['github:' + logical] = provider._request(
                'github', 'GET', provider._github_url(f'issues/{resource}')).json()
        milestone = provider.config['github']['milestone_number']
        records['github:REL'] = provider._request(
            'github', 'GET', provider._github_url(f'milestones/{milestone}')).json()
        for logical, resource in provider.config['calendar']['events'].items():
            records['calendar:' + logical] = provider._request(
                'calendar', 'GET', provider._calendar_url(resource)).json()
    finally:
        provider.client.close()
    return {'captured_at': datetime.now(UTC).isoformat(), 'records': records}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label', choices=['before', 'after', 'final'])
    args = parser.parse_args()
    result = capture()
    path = Path('data') / f'acceptance-{args.label}.json'
    path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(f'Read {len(result["records"])} real records; evidence saved to {path}.')
