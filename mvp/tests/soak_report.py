"""Tong hop bai soak tu raw: soak-samples.jsonl + bao cao load_cutover.  Usage: python3 tests/soak_report.py --run-dir run
Tinh xu huong (do doc theo gio, hoi quy tuyen tinh) cua RAM API, RAM Triton, VRAM; so sanh gio dau va gio cuoi.
Khong ket luan "khong ro ri": chi bao so do va canh bao khi gio cuoi cao hon gio dau qua 10%."""
import argparse
import json
from pathlib import Path


def slope_per_hour(points):
    pts = [(t, v) for t, v in points if v is not None]
    if len(pts) < 3:
        return None
    n = len(pts)
    mt, mv = sum(t for t, _ in pts) / n, sum(v for _, v in pts) / n
    den = sum((t - mt) ** 2 for t, _ in pts)
    return None if den == 0 else sum((t - mt) * (v - mv) for t, v in pts) / den * 3600


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--samples', default='soak-samples.jsonl')
    ap.add_argument('--load-report', default='soak-load-report.json')
    a = ap.parse_args()
    samples = [json.loads(l) for l in (a.run_dir / a.samples).read_text().splitlines() if l.strip()]
    t0, t1 = samples[0]['t'], samples[-1]['t']
    hours = (t1 - t0) / 3600
    out = {'samples': len(samples), 'duration_h': round(hours, 2), 'series': {}}
    for key, unit, div in (('vr01_process_resident_memory_bytes', 'MiB', 2 ** 20), ('api_container_mem_bytes', 'MiB', 2 ** 20),
                           ('triton_container_mem_bytes', 'MiB', 2 ** 20), ('gpu_mem_used_mib', 'MiB', 1),
                           ('gpu_util_pct', '%', 1), ('gpu_temp_c', 'C', 1), ('vr01_queue_depth', 'request', 1)):
        pts = [(s['t'], s.get(key) / div if s.get(key) is not None else None) for s in samples]
        vals = [v for _, v in pts if v is not None]
        if not vals:
            out['series'][key] = None
            continue
        first = [v for t, v in pts if v is not None and t - t0 <= min(3600, (t1 - t0) / 4)]
        last = [v for t, v in pts if v is not None and t1 - t <= min(3600, (t1 - t0) / 4)]
        sl = slope_per_hour(pts)
        fa, la = sum(first) / len(first), sum(last) / len(last)
        out['series'][key] = {'unit': unit, 'min': round(min(vals), 2), 'max': round(max(vals), 2),
                              'first_window_avg': round(fa, 2), 'last_window_avg': round(la, 2),
                              'slope_per_hour': None if sl is None else round(sl, 3),
                              # bo gio dau (khoi dong, cache nong len): do doc nay moi noi ve xu huong dai han
                              'slope_per_hour_after_first_hour': (lambda z: None if z is None else round(z, 3))(
                                  slope_per_hour([(t, v) for t, v in pts if t - t0 > 3600]) if t1 - t0 > 7200 else None),
                              'last_vs_first_pct': None if fa == 0 else round((la - fa) / fa * 100, 2)}
    restarts = sorted({tuple(s.get('container_restarts') or []) for s in samples})
    out['container_restart_counts_seen'] = [list(r) for r in restarts]
    out['process_start_times_seen'] = sorted({s.get('vr01_process_start_time_seconds') for s in samples if s.get('vr01_process_start_time_seconds')})
    out['not_ready_samples'] = sum(1 for s in samples if s.get('vr01_ready') == 0)
    lr = a.run_dir / a.load_report
    if lr.is_file():
        r = json.loads(lr.read_text())
        out['load'] = {'verdict': r['verdict'], 'requests': r['requests'], 'cutovers': {k: r['cutovers'][k] for k in ('requested', 'succeeded', 'max_gap_s')},
                       'latency_total_ms': r['latency_total_ms'], 'client_retries': r['client_retries_same_request_id'], 'config': r['config']}
    grow = [k for k, v in out['series'].items() if v and k.endswith(('bytes', 'mib')) and (v['last_vs_first_pct'] or 0) > 10]
    out['memory_growth_over_10pct'] = grow
    out['no_restart_during_soak'] = len(restarts) <= 1 and len(out['process_start_times_seen']) <= 1
    out['verdict'] = 'PASS' if out.get('load', {}).get('verdict') == 'PASS' and out['no_restart_during_soak'] and not grow else 'REVIEW'
    out['note'] = 'PASS = tai dat + khong restart + khong chuoi bo nho nao tang qua 10% (gio cuoi so voi gio dau). REVIEW = can nguoi xem; khong tu dong la FAIL.'
    (a.run_dir / 'soak-report.json').write_text(json.dumps(out, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({k: out[k] for k in ('verdict', 'duration_h', 'samples', 'memory_growth_over_10pct', 'no_restart_during_soak')}))
    for k, v in out['series'].items():
        if v:
            print(f"  {k:<38} {v['first_window_avg']:>10} -> {v['last_window_avg']:>10} {v['unit']:<8} slope {v['slope_per_hour']}/h")


if __name__ == '__main__':
    main()
