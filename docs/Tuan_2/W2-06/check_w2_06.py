"""W2-06 reviewer check (static, stdlib + PyYAML).  Usage: python3 -I check_w2_06.py --output reviewer-result.json

PASS means: ui-spec.json, the Markdown tables and prototype.html describe the SAME screens/states;
every API operation a screen uses exists in the MVP OpenAPI and is allowed for that screen's roles;
every touch task maps to a screen its role may open; the prototype makes no network call.
PASS does NOT mean the design was reviewed or accepted, nor that a UI is implemented.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ORDER = {'viewer': 0, 'operator': 1, 'admin': 2}


def find_spec():
    for cand in (HERE.parents[2] / 'mvp' / 'backend' / 'openapi.v1.yaml', HERE / 'openapi.v1.yaml'):
        if cand.is_file():
            return cand
    raise SystemExit('cannot find mvp/backend/openapi.v1.yaml')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output', default='reviewer-result.json')
    args = ap.parse_args()
    spec = json.loads((HERE / 'ui-spec.json').read_text(encoding='utf-8'))
    html = (HERE / 'prototype.html').read_text(encoding='utf-8')
    md = (HERE / 'W2-06-UI-UX.md').read_text(encoding='utf-8')
    api = yaml.safe_load(find_spec().read_text(encoding='utf-8'))
    ops = {op['operationId']: set(op.get('x-roles', [])) for item in api['paths'].values()
           for m, op in item.items() if m in ('get', 'post')}
    errors, checks = [], []

    def check(name, ok, detail=''):
        checks.append({'check': name, 'result': 'PASS' if ok else 'FAIL', 'detail': detail})
        if not ok:
            errors.append(f'{name}: {detail}')

    want = {(s['id'], st) for s in spec['screens'] for st in s['states']}
    got = set(re.findall(r"VIEWS\['([a-z]+)/([a-z_]+)'\]\s*=", html))
    check('prototype_has_every_screen_state', want == got, sorted(f'{a}/{b}' for a, b in want ^ got))
    md_states = set()
    for line in md.splitlines():
        m = re.match(r'\|\s*`([a-z]+)`\s*\|\s*`([a-z_]+)`\s*\|', line)
        if m:
            md_states.add(m.groups())
    check('markdown_matrix_equals_spec', md_states == want, sorted(f'{a}/{b}' for a, b in md_states ^ want))
    bad = []
    for s in spec['screens']:
        for op in s['operations']:
            if op not in ops:
                bad.append(f"{s['id']}: {op} not in OpenAPI")
            elif 'anonymous' not in ops[op] and not set(s['roles']) <= ops[op]:
                bad.append(f"{s['id']}: roles {s['roles']} not all allowed for {op} {sorted(ops[op])}")
    check('screen_operations_exist_and_roles_allowed', not bad, bad)
    screens = {s['id']: s for s in spec['screens']}
    bad = [t['id'] for t in spec['tasks'] if t['channel'] == 'touch'
           and (t['screen'] not in screens or t['role'] not in screens[t['screen']]['roles'])]
    check('touch_tasks_map_to_permitted_screens', not bad, bad)
    bad = [t['id'] for t in spec['tasks'] if t['channel'] == 'cli' and t['role'] != 'admin']
    check('cli_tasks_are_admin_only', not bad, bad)
    md_tasks = set(re.findall(r'^\|\s*([KC]\d+)\s*\|', md, flags=re.M))
    check('markdown_task_table_equals_spec', md_tasks == {t['id'] for t in spec['tasks']},
          sorted(md_tasks ^ {t['id'] for t in spec['tasks']}))
    md_gaps = set(re.findall(r'^\|\s*(U\d+)\s*\|', md, flags=re.M))
    check('markdown_gap_table_equals_spec', md_gaps == {g['id'] for g in spec['api_gaps']}, sorted(md_gaps))
    for need in ('permission', 'error', 'loading'):
        missing = [s['id'] for s in spec['screens'] if need not in s['states']
                   and not (need == 'permission' and set(s['roles']) == set(spec['roles']))
                   and not (need in ('loading', 'error') and s['id'] == 'inspect')]
        check(f'every_screen_has_{need}_state', not missing, missing)
    check('history_has_empty_state', 'empty' in screens['history']['states'])
    net = re.findall(r'\b(fetch\(|XMLHttpRequest|WebSocket|<script[^>]+src=|<link[^>]+href=|@import|https?://)', html)
    check('prototype_is_self_contained_no_network', not net, net)
    check('technical_error_never_shown_as_ok_or_ng',
          'Đây không phải OK và không phải NG' in html and 'CHƯA CÓ KẾT LUẬN' in html)
    check('dangerous_actions_have_confirm_dialog',
          all(k in html for k in ("recipe/confirm_activate", "recipe/confirm_rollback", 'role="dialog"')))
    result = {'check': 'W2-06 UI/UX', 'spec_version': spec['version'], 'verdict': 'PASS' if not errors else 'FAIL',
              'screens': len(spec['screens']), 'screen_states': len(want), 'checks': checks, 'errors': errors,
              'meaning': 'Static consistency only. No design review has taken place; no UI is implemented.'}
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"W2-06 check: {result['verdict']}  {sum(c['result'] == 'PASS' for c in checks)}/{len(checks)} checks, "
          f"{len(want)} screen-states  -> {args.output}")
    for e in errors:
        print('  ERROR:', e)
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
