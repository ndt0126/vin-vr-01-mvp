"""Ve bieu do soak (SVG, chi dung thu vien chuan) tu soak-samples.jsonl.  Usage: python3 tests/soak_chart.py --run-dir run
Moi o la mot chuoi theo thoi gian (gio ke tu luc bat dau). Truc Y bat dau tu 0 de khong phong dai dao dong nho."""
import argparse
import json
from pathlib import Path

SERIES = (('vr01_process_resident_memory_bytes', 'RAM tiến trình API (MiB)', 2 ** 20),
          ('triton_container_mem_bytes', 'RAM container Triton (MiB)', 2 ** 20),
          ('gpu_mem_used_mib', 'VRAM đã dùng (MiB)', 1), ('gpu_util_pct', 'GPU bận (%)', 1),
          ('gpu_temp_c', 'Nhiệt độ GPU (°C)', 1), ('vr01_queue_depth', 'Request chưa kết thúc', 1))
W, H, PAD_L, PAD_B, PAD_T = 560, 190, 62, 26, 26


def panel(samples, key, title, div, x0, y0, t0, hours):
    pts = [((s['t'] - t0) / 3600, s[key] / div) for s in samples if s.get(key) is not None]
    out = [f'<text x="{x0 + PAD_L}" y="{y0 + 16}" font-size="13" font-weight="bold">{title}</text>']
    if not pts:
        return out + [f'<text x="{x0 + PAD_L}" y="{y0 + 60}" font-size="12">không có dữ liệu</text>']
    top = max(v for _, v in pts) * 1.1 or 1
    pw, ph = W - PAD_L - 12, H - PAD_T - PAD_B
    fx = lambda h: x0 + PAD_L + h / max(hours, 1e-9) * pw   # noqa: E731
    fy = lambda v: y0 + PAD_T + ph - v / top * ph            # noqa: E731
    out.append(f'<rect x="{x0 + PAD_L}" y="{y0 + PAD_T}" width="{pw}" height="{ph}" fill="none" stroke="#999"/>')
    for i in range(5):
        v = top * i / 4
        out.append(f'<line x1="{x0 + PAD_L}" x2="{x0 + PAD_L + pw}" y1="{fy(v):.1f}" y2="{fy(v):.1f}" stroke="#ddd"/>')
        out.append(f'<text x="{x0 + PAD_L - 6}" y="{fy(v) + 4:.1f}" font-size="11" text-anchor="end">{v:,.0f}</text>' if top >= 10 else f'<text x="{x0 + PAD_L - 6}" y="{fy(v) + 4:.1f}" font-size="11" text-anchor="end">{v:.2f}</text>')
    for h in range(int(hours) + 1):
        out.append(f'<text x="{fx(h):.1f}" y="{y0 + H - 8}" font-size="11" text-anchor="middle">{h} h</text>')
    out.append('<polyline fill="none" stroke="#1f5fbf" stroke-width="1.2" points="'
               + ' '.join(f'{fx(h):.1f},{fy(v):.1f}' for h, v in pts) + '"/>')
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--samples', default='soak-samples.jsonl')
    ap.add_argument('--output', default='soak-charts.svg')
    a = ap.parse_args()
    samples = [json.loads(l) for l in (a.run_dir / a.samples).read_text().splitlines() if l.strip()]
    t0, hours = samples[0]['t'], (samples[-1]['t'] - samples[0]['t']) / 3600
    rows = (len(SERIES) + 1) // 2
    body = [f'<text x="12" y="20" font-size="14" font-weight="bold">Soak: {hours:.2f} giờ, {len(samples)} mẫu '
            f'(mỗi {round((samples[1]["t"] - t0)) if len(samples) > 1 else "?"} giây). Trục Y bắt đầu từ 0.</text>']
    for i, (key, title, div) in enumerate(SERIES):
        body += panel(samples, key, title, div, (i % 2) * W, 30 + (i // 2) * H, t0, hours)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{2 * W}" height="{40 + rows * H}" font-family="sans-serif">'
           f'<rect width="100%" height="100%" fill="white"/>' + ''.join(body) + '</svg>\n')
    (a.run_dir / a.output).write_text(svg, encoding='utf-8')
    print(f'wrote {a.run_dir / a.output}: {len(samples)} samples, {hours:.2f} h')


if __name__ == '__main__':
    main()
