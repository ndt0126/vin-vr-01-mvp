"""In toan bo duong di cua MOT request tu ledger + trace log + audit (W4-02).

Usage: python3 tools/trace_request.py --run-dir run <request_id> [--json]
Doc truc tiep file trong run/data (ca trace da xoay vong); khong can token, khong goi API.
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path


def collect(run, rid):
    data = run / 'data'
    db = sqlite3.connect(f'file:{data / "ledger.sqlite3"}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    row = db.execute('SELECT * FROM inspections WHERE request_id=?', (rid,)).fetchone()
    if row is None:
        return None
    row = dict(row)
    pin = json.loads(row.pop('pin_json'))
    chain = [dict(r) for r in db.execute(
        'SELECT request_id, state, decision, reason, retry_of, received_at FROM inspections WHERE product_id=? ORDER BY seq',
        (row['product_id'],))]
    audit = [dict(r) for r in db.execute('SELECT at, actor, role, action, outcome, details FROM audit WHERE target=? ORDER BY seq',
                                         (rid,))]
    events = []
    files = sorted(data.glob('trace.jsonl*'), key=lambda p: (p.name != 'trace.jsonl', p.name), reverse=True)
    for f in files:  # file cu nhat truoc
        for line in f.read_text(encoding='utf-8').splitlines():
            e = json.loads(line)
            if e.get('request_id') == rid or e.get('trace_id') == row['trace_id'] or e.get('target') == rid:
                events.append(e)
    events.sort(key=lambda e: e['at'])
    return {'request': row, 'pinned': pin, 'events': events, 'audit': audit, 'attempts_for_product': chain}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('request_id')
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()
    t = collect(a.run_dir, a.request_id)
    if t is None:
        print(f'request {a.request_id} not found in ledger')
        return 1
    if a.json:
        print(json.dumps(t, indent=2, ensure_ascii=False))
        return 0
    r, p = t['request'], t['pinned']
    print(f"request_id   {r['request_id']}\nproduct_id   {r['product_id']}   station {r['station_id']}   gui boi {r['submitted_by']}")
    print(f"trace_id     {r['trace_id']}")
    print(f"anh          sha256 {r['input_sha256']}   file {r['image_path']}   chup luc {r['captured_at']}")
    print(f"da pin       recipe {p['recipe']['name']}@{p['recipe']['version']} ({p['recipe']['sha256'][:12]})   "
          f"model {p['model']['name']}@{p['model']['version']} ({p['model']['manifest_sha256'][:12]})   nguong {p['threshold']} ±{p['review_band']}")
    print(f"ket qua      state {r['state']}   decision {r['decision']}   score {r['score']}   reason {r['reason']}")
    print(f"thoi gian    nhan {r['received_at']}   bat dau {r['started_at']}   ket thuc {r['finished_at']}   "
          f"cho {r['queue_ms']} ms   suy luan {r['inference_ms']} ms   tong {r['total_ms']} ms")
    print('\nSu kien (trace log):')
    for e in t['events']:
        extra = {k: v for k, v in e.items() if k not in ('at', 'event', 'request_id', 'trace_id', 'model', 'recipe',
                                                         'input_sha256', 'product_id', 'station_id')}
        print(f"  {e['at']}  {e['event']:<38} {json.dumps(extra, ensure_ascii=False) if extra else ''}")
    if t['audit']:
        print('\nAudit:')
        for x in t['audit']:
            print(f"  {x['at']}  {x['actor']} ({x['role']})  {x['action']} -> {x['outcome']}  {x['details']}")
    if len(t['attempts_for_product']) > 1:
        print('\nMoi lan kiem cua san pham nay:')
        for c in t['attempts_for_product']:
            print(f"  {c['received_at']}  {c['request_id']}  {c['state']} {c['decision'] or ''} {c['reason'] or ''}"
                  + (f"  (kiem lai cua {c['retry_of']})" if c['retry_of'] else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
