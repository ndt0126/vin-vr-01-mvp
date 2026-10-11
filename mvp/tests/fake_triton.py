"""Inference server GIA (KServe v2 + explicit model control) de thu manifests/stack khi khong co Triton that.
Usage: python tests/fake_triton.py --examples /run-data/examples [--port 8000] [--host 127.0.0.1]
KHONG phai bang chung ve Triton."""
import argparse
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'backend'))
from test_contract import FakeKServe  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--examples', type=Path, required=True)
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--host', default='127.0.0.1')
    a = ap.parse_args()
    import test_contract
    models = {d.name: json.loads((d / 'model.json').read_text()) for d in (a.examples / 'packages').iterdir() if (d / 'model.json').is_file()}
    orig = test_contract.ThreadingHTTPServer

    class Bound(orig):
        def __init__(self, addr, handler):
            super().__init__((a.host, a.port), handler)

    test_contract.ThreadingHTTPServer = Bound
    fake = FakeKServe(models)
    fake.delays['model-slow'] = 0.8
    fake.fail_above['model-bad'] = 0.5
    for d in (a.examples / 'packages').iterdir():
        if (d / 'model.onnx').is_file():
            fake.onnx[d.name] = str(d / 'model.onnx')
    print(f'FAKE inference server on {fake.url} models={sorted(models)}', flush=True)
    threading.Event().wait()


if __name__ == '__main__':
    main()
