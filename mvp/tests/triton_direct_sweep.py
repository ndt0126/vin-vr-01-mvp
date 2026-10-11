"""Quet theo SO INSTANCE va MUC DONG THOI, goi THANG Triton (KServe v2, tensor nhi phan), khong qua Inspection API.

Muc dich: Inspection API hien gui tung request qua 1 worker, nen bai load_sweep.py chi do duoc tran cua 1 instance.
Bai nay tra loi cau hoi khac: GPU con du bao nhieu nang luc neu tang so instance cua model va gui song song.
Day KHONG phai duong di cua request san xuat (khong ledger, khong pin recipe); chi la so do cua inference server.

Cach chay: recipe dang active phai KHONG dung model duoc quet (vd dang o recipe-a), vi bai nay tu nap/go model do.
  python3 tests/triton_direct_sweep.py --run-dir run --triton http://<ip-container-triton>:8000 --model model-heavy
Moi o (instances x concurrency) la vong kin: C luong, moi luong gui lien tiep trong --seconds giay.
Sua `count:` trong config.pbtxt cua model roi nap lai; ket thuc thi tra config ve nguyen trang va go model.
"""
import argparse
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def call(base, method, path, body=None, headers=None, timeout=120):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001  (mat ket noi: dem la loi, khong lam chet ca bai)
        return 599, repr(e).encode()


def pct(v, p):
    v = sorted(v)
    return round(v[min(len(v) - 1, int(len(v) * p / 100))], 1) if v else None


def gpu():
    try:
        out = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu', '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, timeout=10).stdout.strip().split(',')
        return {'vram_mib': float(out[0]), 'util_pct': float(out[1])}
    except Exception:  # noqa: BLE001  (may dev khong co GPU)
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--triton', required=True, help='vd http://172.18.0.2:8000')
    ap.add_argument('--model', default='model-heavy')
    ap.add_argument('--instances', default='1,2,4')
    ap.add_argument('--concurrency', default='1,2,4,8')
    ap.add_argument('--seconds', type=float, default=20)
    ap.add_argument('--output', type=Path)
    a = ap.parse_args()
    cfg_path = a.run_dir / 'triton-repo' / a.model / 'config.pbtxt'
    original = cfg_path.read_text()
    size = int(re.search(r'dims: \[1, 3, (\d+), \d+\]', original).group(1))
    tensor = bytes((i * 7) % 256 for i in range(3 * size * size))
    header = json.dumps({'id': 'direct-sweep', 'inputs': [{'name': 'IMAGE', 'shape': [1, 3, size, size], 'datatype': 'UINT8',
                                     'parameters': {'binary_data_size': len(tensor)}}],
                         'outputs': [{'name': 'SCORE', 'parameters': {'binary_data': False}}]}).encode()
    hdrs = {'Content-Type': 'application/octet-stream', 'Inference-Header-Content-Length': str(len(header))}
    cells, scores = [], set()
    try:
        for n in [int(x) for x in a.instances.split(',')]:
            cfg_path.write_text(re.sub(r'count: \d+', f'count: {n}', original))
            t0 = time.time()
            s, b = call(a.triton, 'POST', f'/v2/repository/models/{a.model}/load', {}, timeout=600)
            if s != 200:
                cells.append({'instances': n, 'load_failed': b.decode(errors='replace')[:300]})
                print(f'instances {n}: LOAD FAILED {s} {b[:200]!r}', flush=True)
                continue
            load_s = round(time.time() - t0, 1)
            for _ in range(n * 2):      # lam nong moi instance (lan dau moi instance cap bo nho)
                call(a.triton, 'POST', f'/v2/models/{a.model}/infer', header + tensor, hdrs, 300)
            for c in [int(x) for x in a.concurrency.split(',')]:
                lat, errors, lock, stop = [], [], threading.Lock(), time.time() + a.seconds

                def worker():
                    while time.time() < stop:
                        t = time.time()
                        st, body = call(a.triton, 'POST', f'/v2/models/{a.model}/infer', header + tensor, hdrs, 300)
                        with lock:
                            if st == 200:
                                lat.append((time.time() - t) * 1000)
                                scores.add(round(json.loads(body)['outputs'][0]['data'][0], 3))   # 3 chu so: cac instance GPU co the lech o chu so nho
                            else:
                                errors.append(f'{st} {body[:120]!r}')
                started = time.time()
                threads = [threading.Thread(target=worker) for _ in range(c)]
                [t.start() for t in threads]
                time.sleep(a.seconds / 2)
                mid = gpu()
                [t.join() for t in threads]
                wall = time.time() - started
                cell = {'instances': n, 'concurrency': c, 'completed': len(lat), 'errors': len(errors), 'error_samples': errors[:2],
                        'throughput_rps': round(len(lat) / wall, 3), 'latency_ms': {'p50': pct(lat, 50), 'p95': pct(lat, 95), 'p99': pct(lat, 99)},
                        'gpu_mid_run': mid, 'load_s': load_s}
                cells.append(cell)
                print(f"instances {n} concurrency {c:>2}: {cell['throughput_rps']:>7.2f} req/s  p50 {cell['latency_ms']['p50']} ms  "
                      f"p95 {cell['latency_ms']['p95']} ms  errors {len(errors)}  gpu {mid}", flush=True)
    finally:
        cfg_path.write_text(original)
        call(a.triton, 'POST', f'/v2/repository/models/{a.model}/unload', {})
    ok = [x for x in cells if x.get('completed')]
    best = max(ok, key=lambda x: x['throughput_rps'], default=None)
    report = {'model': a.model, 'input_size': size, 'seconds_per_cell': a.seconds, 'cells': cells,
              'distinct_scores_for_the_same_input': sorted(scores), 'best': best,
              'note': 'Goi thang Triton, vong kin; khong qua Inspection API/ledger. Model fixture, khong phai model QC.'}
    out = a.output or a.run_dir / 'triton-direct-sweep-report.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(f"DIRECT SWEEP done: best {best['throughput_rps'] if best else None} req/s "
          f"(instances {best['instances'] if best else '-'}, concurrency {best['concurrency'] if best else '-'}); "
          f"same input -> {len(scores)} distinct score(s)  -> {out}")
    return 0 if ok and all(x.get('errors', 0) == 0 for x in ok) and len(scores) == 1 else 1


if __name__ == '__main__':
    raise SystemExit(main())
