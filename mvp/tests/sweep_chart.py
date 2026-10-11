"""Ve bieu do quet tai (SVG, thu vien chuan) tu bao cao cua load_sweep.py.
Usage: python3 tests/sweep_chart.py <load-sweep-report.json> [output.svg]
O trai: throughput hoan tat theo toc do gui (duong cheo = ly tuong). O phai: p50/p95/p99 theo toc do gui."""
import json
import sys
from pathlib import Path

W, H, L, B, T = 520, 300, 64, 40, 34


def axes(x0, title, xmax, ymax, xlabel, ylabel):
    pw, ph = W - L - 16, H - T - B
    fx = lambda v: x0 + L + v / xmax * pw   # noqa: E731
    fy = lambda v: T + ph - v / ymax * ph   # noqa: E731
    out = [f'<text x="{x0 + L}" y="20" font-size="13" font-weight="bold">{title}</text>',
           f'<rect x="{x0 + L}" y="{T}" width="{pw}" height="{ph}" fill="none" stroke="#999"/>',
           f'<text x="{x0 + L + pw / 2}" y="{H - 6}" font-size="11" text-anchor="middle">{xlabel}</text>',
           f'<text x="{x0 + 12}" y="{T + ph / 2}" font-size="11" text-anchor="middle" transform="rotate(-90 {x0 + 12} {T + ph / 2})">{ylabel}</text>']
    for i in range(5):
        v = ymax * i / 4
        out.append(f'<line x1="{x0 + L}" x2="{x0 + L + pw}" y1="{fy(v):.1f}" y2="{fy(v):.1f}" stroke="#ddd"/>')
        out.append(f'<text x="{x0 + L - 6}" y="{fy(v) + 4:.1f}" font-size="11" text-anchor="end">{v:,.2f}</text>' if ymax < 10 else
                   f'<text x="{x0 + L - 6}" y="{fy(v) + 4:.1f}" font-size="11" text-anchor="end">{v:,.0f}</text>')
        u = xmax * i / 4
        out.append(f'<text x="{fx(u):.1f}" y="{T + ph + 14}" font-size="11" text-anchor="middle">{u:g}</text>')
    return out, fx, fy


def line(pts, fx, fy, color, label, idx, x0):
    out = [f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="' + ' '.join(f'{fx(x):.1f},{fy(y):.1f}' for x, y in pts) + '"/>']
    out += [f'<circle cx="{fx(x):.1f}" cy="{fy(y):.1f}" r="3" fill="{color}"/>' for x, y in pts]
    out.append(f'<text x="{x0 + L + 10}" y="{T + 16 + idx * 15}" font-size="11" fill="{color}">{label}</text>')
    return out


def main():
    src = Path(sys.argv[1])
    r = json.loads(src.read_text())
    steps = r['steps']
    xmax = max(s['target_rps'] for s in steps)
    body, fx, fy = axes(0, f"Throughput — {r['recipe']}", xmax, xmax, 'tốc độ gửi (request/giây)', 'hoàn tất (request/giây)')
    body += line([(0, 0), (xmax, xmax)], fx, fy, '#bbb', 'lý tưởng (hoàn tất = gửi)', 0, 0)[:1]
    body += line([(s['target_rps'], s['achieved_completed_rps']) for s in steps], fx, fy, '#1f5fbf', 'hoàn tất', 0, 0)
    lmax = max(s['latency_total_ms']['p99'] or 0 for s in steps) * 1.1 or 1
    b2, fx2, fy2 = axes(W, 'Độ trễ toàn trình (ms)', xmax, lmax, 'tốc độ gửi (request/giây)', 'ms')
    for i, (k, c) in enumerate((('p50', '#2a9d4b'), ('p95', '#d98200'), ('p99', '#c0392b'))):
        b2 += line([(s['target_rps'], s['latency_total_ms'][k] or 0) for s in steps], fx2, fy2, c, k, i, W)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name(src.stem.replace('-report', '') + '-chart.svg')
    out.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{2 * W}" height="{H}" font-family="sans-serif">'
                   '<rect width="100%" height="100%" fill="white"/>' + ''.join(body + b2) + '</svg>\n', encoding='utf-8')
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
