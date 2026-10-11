"""Sao luu / khoi phuc du lieu MVP (ledger + trace + anh) trong run/.

  python3 tools/backup.py backup  --run-dir run [--dest run/backup]     # chay duoc khi stack DANG bat
  python3 tools/backup.py restore --run-dir run --from run/backup/<ten>  # stack phai DA dung (make stop)

backup: ledger bang SQLite online backup API (nhat quan khi dang ghi) + PRAGMA integrity_check,
        trace.jsonl va thu muc images/ duoc copy, MANIFEST.sha256 cho moi file.
restore: kiem MANIFEST truoc, tu choi neu sai; du lieu hien tai duoc DOI TEN thanh data.before-restore-<gio> (khong xoa).
Gioi han: dich mac dinh nam tren CUNG may (khong bao ve khi hong o); trace co the thieu vai dong ghi sau luc chup ledger.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def manifest(root):
    return {str(p.relative_to(root)): sha(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'MANIFEST.sha256'}


def backup(run, dest):
    data = run / 'data'
    out = dest / time.strftime('backup-%Y%m%dT%H%M%SZ', time.gmtime())
    out.mkdir(parents=True)
    t0 = time.time()
    src = sqlite3.connect(str(data / 'ledger.sqlite3'))
    dst = sqlite3.connect(str(out / 'ledger.sqlite3'))
    src.backup(dst)
    integrity = dst.execute('PRAGMA integrity_check').fetchone()[0]
    rows = dst.execute('SELECT COUNT(*) FROM inspections').fetchone()[0]
    dst.close()
    src.close()
    if integrity != 'ok':
        raise SystemExit(f'backup integrity_check failed: {integrity}')
    for tf in sorted(data.glob('trace.jsonl*')):  # ca cac file da xoay vong
        shutil.copy2(tf, out / tf.name)
    if (data / 'images').is_dir():
        shutil.copytree(data / 'images', out / 'images', ignore=shutil.ignore_patterns('.*.tmp'))
    m = manifest(out)
    (out / 'MANIFEST.sha256').write_text(''.join(f'{h}  {name}\n' for name, h in m.items()))
    info = {'backup': str(out), 'integrity_check': integrity, 'inspections': rows, 'files': len(m),
            'images': sum(1 for n in m if n.startswith('images/')), 'has_trace': 'trace.jsonl' in m,
            'seconds': round(time.time() - t0, 2)}
    print(json.dumps(info))
    return info


def restore(run, source):
    want = {}
    for line in (source / 'MANIFEST.sha256').read_text().splitlines():
        h, name = line.split('  ', 1)
        want[name] = h
    got = manifest(source)
    if got != want:
        bad = sorted(set(want) ^ set(got)) or sorted(n for n in want if got.get(n) != want[n])
        raise SystemExit(f'backup does not match its MANIFEST, refusing to restore: {bad[:5]}')
    data = run / 'data'
    if (data / 'ledger.sqlite3-wal').exists() and (data / 'ledger.sqlite3-wal').stat().st_size:
        print('note: current data has a non-empty WAL; make sure the stack is stopped', file=sys.stderr)
    kept = None
    if data.exists():
        kept = run / time.strftime('data.before-restore-%Y%m%dT%H%M%SZ', time.gmtime())
        data.rename(kept)
    shutil.copytree(source, data, ignore=shutil.ignore_patterns('MANIFEST.sha256'))
    db = sqlite3.connect(str(data / 'ledger.sqlite3'))
    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    rows = db.execute('SELECT COUNT(*) FROM inspections').fetchone()[0]
    db.close()
    info = {'restored_from': str(source), 'integrity_check': integrity, 'inspections': rows, 'files': len(want),
            'previous_data_kept_as': str(kept) if kept else None}
    print(json.dumps(info))
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=['backup', 'restore'])
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--dest', type=Path)
    ap.add_argument('--from', dest='source', type=Path)
    a = ap.parse_args()
    if a.action == 'backup':
        backup(a.run_dir, a.dest or a.run_dir / 'backup')
    else:
        if not a.source:
            ap.error('restore needs --from <backup dir>')
        restore(a.run_dir, a.source)


if __name__ == '__main__':
    main()
