"""Compare independent raw provider readbacks against the actual approved live plan."""
import argparse
import json
from copy import deepcopy
from pathlib import Path


def read(name):
    return json.loads((Path('data') / name).read_text(encoding='utf-8'))


def stable(record, provider):
    result = deepcopy(record)
    # Provider-owned revision metadata changes on a legitimate write.
    for key in ('last_edited_time', 'last_edited_by', 'request_id') if provider == 'notion' else (
        ('updated', 'etag', 'sequence') if provider == 'calendar' else ('updated_at',)
    ):
        result.pop(key, None)
    # GitHub embeds current milestone metadata in each linked issue response.
    if provider == 'github' and result.get('milestone'):
        result['milestone'].pop('updated_at', None)
        result['milestone'].pop('due_on', None)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--final', action='store_true', help='Verify after the interruption/restoration tests')
    args = parser.parse_args()
    before = read('acceptance-before.json')['records']
    after = read('acceptance-final.json' if args.final else 'acceptance-after.json')['records']
    plan = read('acceptance-plan.json')
    operations = {op['record_key']: op for op in plan['operations']}
    if args.final:
        restoration = read('acceptance-restoration-plan.json')
        assert restoration['proposed_date'] == '2026-09-24'
        operations.update({op['record_key']: op for op in restoration['operations']})
    assert before.keys() == after.keys(), 'Record membership changed'
    changes, unchanged = [], []
    for key, record in before.items():
        provider = key.split(':')[0]
        expected = stable(record, provider)
        actual = stable(after[key], provider)
        op = operations.get(key)
        if op:
            for field, value in op['after'].items():
                if provider == 'calendar':
                    expected[field]['dateTime'] = value
                elif provider == 'github':
                    expected[field] = value
                elif field == 'Schedule':
                    expected['properties']['Schedule']['date'] = {
                        'start': value['start'],
                        'end': value['end'],
                        'time_zone': None,
                    }
                elif field == 'DeliveryDate':
                    expected['properties']['Delivery date']['date'] = {
                        'start': value, 'end': None, 'time_zone': None,
                    }
                elif field == 'AcceptedPlan':
                    text = expected['properties']['Accepted plan']['rich_text']
                    assert len(text) == 1 and text[0]['type'] == 'text'
                    text[0]['text']['content'] = value
                    text[0]['plain_text'] = value
                else:
                    raise AssertionError(f'Unexpected approved field: {key}/{field}')
            changes.append(key)
        else:
            unchanged.append(key)
        assert actual == expected, f'Unexpected source-field difference: {key}'
        # Unchanged calendar events must retain even their exact revision metadata.
        if provider == 'calendar' and not op:
            assert record == after[key], f'Unrelated calendar event changed: {key}'
        if provider == 'notion' and not op:
            assert {k: v for k, v in record.items() if k != 'request_id'} == {
                k: v for k, v in after[key].items() if k != 'request_id'
            }, f'Unchanged Notion page revision changed: {key}'
    result = {'passed': True, 'approved_records_changed': changes,
              'protected_records_preserved': unchanged, 'records_checked': len(before),
              'comparison': 'Full raw provider records, excluding request IDs, automatic revision metadata '
                            'and the embedded milestone date projection in linked issues.'}
    name = 'acceptance-final-verification.json' if args.final else 'acceptance-independent-verification.json'
    (Path('data') / name).write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
