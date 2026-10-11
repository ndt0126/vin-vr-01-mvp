"""Lay mau tai nguyen dinh ky cho bai soak (W4-04): RAM tien trinh API, RAM container, VRAM/GPU, hang doi, so dem.
Usage: python3 tests/sampler.py --out run/soak-samples.jsonl [--interval 30]   (chay nen, dung bang SIGTERM)
Moi dong mot mau JSON. Thieu nvidia-smi hoac docker thi truong tuong ung la null."""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

API, TRITON = 'vr01-mvp-api-1', 'vr01-mvp-triton-1'
WANT = ('vr01_process_resident_memory_bytes', 'vr01_queue_depth', 'vr01_ready', 'vr01_storage_free_bytes',
        'vr01_process_cpu_seconds_total', 'vr01_process_start_time_seconds')


def sh(cmd, timeout=15):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:  # noqa: BLE001
        return ''


def mem_bytes(text):
    m = re.match(r'([0-9.]+)\s*([KMG]i?B)', text.strip())
    if not m:
        return None
    return int(float(m.group(1)) * {'KiB': 2 ** 10, 'MiB': 2 ** 20, 'GiB': 2 ** 30, 'KB': 1e3, 'MB': 1e6, 'GB': 1e9}[m.group(2)])


def sample():
    s = {'t': time.time()}
    metrics = sh(f"docker exec {API} python -c \"import urllib.request as u;print(u.urlopen('http://localhost:9090/metrics',timeout=5).read().decode())\"")
    for line in metrics.splitlines():
        if line.startswith(WANT) and ' ' in line and '{' not in line:
            k, v = line.split(' ', 1)
            s[k] = float(v)
    s['terminal_total'] = sum(float(l.rsplit(' ', 1)[1]) for l in metrics.splitlines() if l.startswith('vr01_inspections_terminal_total{'))
    s['terminal_not_completed'] = sum(float(l.rsplit(' ', 1)[1]) for l in metrics.splitlines()
                                      if l.startswith('vr01_inspections_terminal_total{') and 'state="COMPLETED"' not in l)
    for name, key in ((API, 'api_container_mem_bytes'), (TRITON, 'triton_container_mem_bytes')):
        out = sh(f"docker stats --no-stream --format '{{{{.MemUsage}}}}' {name}")
        s[key] = mem_bytes(out.split('/')[0]) if out else None
    s['container_restarts'] = sh(f"docker inspect -f '{{{{.RestartCount}}}} ' {API} {TRITON}").split() or None
    gpu = sh('nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader,nounits')
    if gpu.strip():
        used, total, util, temp = [float(x) for x in gpu.strip().splitlines()[0].split(',')]
        s.update(gpu_mem_used_mib=used, gpu_mem_total_mib=total, gpu_util_pct=util, gpu_temp_c=temp)
    else:
        s.update(gpu_mem_used_mib=None, gpu_util_pct=None)
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--interval', type=float, default=30)
    a = ap.parse_args()
    with open(a.out, 'a', buffering=1) as fh:
        while True:
            t0 = time.time()
            fh.write(json.dumps(sample()) + '\n')
            time.sleep(max(1.0, a.interval - (time.time() - t0)))


if __name__ == '__main__':
    main()
