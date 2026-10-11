"""Thu thap goi chan doan (diagnostic bundle) de gui cho ky su ho tro. KHONG chua token, private key hay anh.

Usage: python3 tools/diag_bundle.py --run-dir run [--out run/diag]
Gom: trang thai readyz/active, dem ledger theo trang thai, 20 lan kiem loi ky thuat gan nhat, audit gan nhat,
2000 dong cuoi cua trace log, metrics hien tai (neu lay duoc), thong tin may, docker ps + log container (neu co docker).
"""
import argparse
import json
import platform
import shutil
import sqlite3
import ssl
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path


def run(cmd):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return (p.stdout + p.stderr)[-200000:]
    except Exception as exc:  # noqa: BLE001
        return f'(khong chay duoc: {exc})'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--out', type=Path)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--inference-port', type=int, default=8443)
    a = ap.parse_args()
    run_dir = a.run_dir
    name = time.strftime('vr01-diag-%Y%m%dT%H%M%SZ', time.gmtime())
    out = (a.out or run_dir / 'diag') / name
    out.mkdir(parents=True)
    info = {'created': name, 'platform': platform.platform(), 'python': platform.python_version()}
    try:
        ctx = ssl.create_default_context(cafile=str(run_dir / 'tls' / 'ca.crt'))
        with urllib.request.urlopen(f'https://{a.host}:{a.inference_port}/readyz', timeout=5, context=ctx) as r:
            info['readyz'] = {'status': r.status, 'body': json.loads(r.read())}
    except urllib.error.HTTPError as e:
        info['readyz'] = {'status': e.code, 'body': json.loads(e.read() or b'null')}
    except Exception as exc:  # noqa: BLE001
        info['readyz'] = {'error': f'{type(exc).__name__}: {exc}'}
    data = run_dir / 'data'
    try:
        db = sqlite3.connect(f'file:{data / "ledger.sqlite3"}?mode=ro', uri=True)
        db.row_factory = sqlite3.Row
        info['ledger'] = {
            'integrity_check': db.execute('PRAGMA integrity_check').fetchone()[0],
            'by_state': dict(db.execute('SELECT state, COUNT(*) FROM inspections GROUP BY state').fetchall()),
            'last_activations': [dict(r) for r in db.execute(
                'SELECT activation_id, at, actor, reason, to_json FROM activations ORDER BY activation_id DESC LIMIT 5')],
            'recent_technical': [dict(r) for r in db.execute(
                "SELECT request_id, product_id, state, reason, received_at, finished_at FROM inspections"
                " WHERE state IN ('FAILED','TIMEOUT','INDETERMINATE') ORDER BY seq DESC LIMIT 20")],
            'recent_audit': [dict(r) for r in db.execute(
                'SELECT at, actor, role, action, target, outcome FROM audit ORDER BY seq DESC LIMIT 50')]}
    except Exception as exc:  # noqa: BLE001
        info['ledger'] = {'error': f'{type(exc).__name__}: {exc}'}
    (out / 'summary.json').write_text(json.dumps(info, indent=2, ensure_ascii=False) + '\n')
    trace = data / 'trace.jsonl'
    if trace.is_file():
        (out / 'trace-tail.jsonl').write_text('\n'.join(trace.read_text(encoding='utf-8').splitlines()[-2000:]) + '\n')
    usage = shutil.disk_usage(run_dir)
    (out / 'host.txt').write_text(
        f'disk total {usage.total} used {usage.used} free {usage.free}\n\n' + run('uname -a; uptime; free -m 2>/dev/null; df -h'))
    if shutil.which('docker'):
        (out / 'docker.txt').write_text(run('docker ps -a --format "{{.Names}} {{.Image}} {{.Status}}"; docker version --format "{{.Server.Version}}"'))
        for c in ('vr01-mvp-api-1', 'vr01-mvp-triton-1'):
            (out / f'{c}.log').write_text(run(f'docker logs --tail 500 {c}'))
        (out / 'metrics.txt').write_text(run(
            "docker exec vr01-mvp-api-1 python -c \"import urllib.request as u;print(u.urlopen('http://localhost:9090/metrics',timeout=5).read().decode())\""))
    tar = out.with_suffix('.tar.gz')
    with tarfile.open(tar, 'w:gz') as tf:
        tf.add(out, arcname=name)
    shutil.rmtree(out)
    print(f'diagnostic bundle: {tar}  ({tar.stat().st_size} bytes)')
    print('Goi nay khong chua token, private key hay anh. Kiem tra lai truoc khi gui ra ngoai nha may.')


if __name__ == '__main__':
    main()
