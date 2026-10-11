"""Chay stack MVP tren may dev KHONG can Docker: Inspection API that (HTTPS) + inference server GIA.

Chi de thu init_lab.py va smoke.py khi chua co Docker/Triton. KHONG phai bang chung Triton that.
Usage: python3 tests/local_stack.py --run-dir run   (Ctrl+C de dung)
"""
import argparse
import json
import signal
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(HERE), str(HERE.parent / 'backend')]
from test_contract import FakeKServe  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--inference-port', default='8443')
    ap.add_argument('--management-port', default='9443')
    args = ap.parse_args()
    run = args.run_dir
    pk = HERE.parent / 'packages' / 'examples' / 'packages'
    fake = FakeKServe({d.name: json.loads((d / 'model.json').read_text()) for d in pk.iterdir() if d.is_dir()})
    proc = subprocess.Popen([sys.executable, '-B', str(HERE.parent / 'backend' / 'inspection_api.py'),
                             '--data-dir', str(run / 'data'), '--principals', str(run / 'auth' / 'principals.json'),
                             '--tls-cert', str(run / 'tls' / 'server.crt'), '--tls-key', str(run / 'tls' / 'server.key'),
                             '--inference-port', args.inference_port, '--management-port', args.management_port,
                             '--kserve-url', fake.url])
    print(f'FAKE inference server at {fake.url}; API starting (pid {proc.pid})', flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # kill wrapper -> van tat API con
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        proc.wait(10)
        fake.close()


if __name__ == '__main__':
    main()
