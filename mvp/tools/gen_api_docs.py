"""Sinh tai lieu API (Markdown) tu backend/openapi.v1.yaml.  Usage: python3 tools/gen_api_docs.py [--check]

--check: khong ghi file, tra exit 1 neu docs/API.md khac noi dung sinh ra (dung trong test de tai lieu khong lech spec).
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SPEC, OUT = ROOT / 'backend' / 'openapi.v1.yaml', ROOT / 'docs' / 'API.md'


def resolve(doc, node):
    while isinstance(node, dict) and '$ref' in node:
        cur = doc
        for part in node['$ref'][2:].split('/'):
            cur = cur[part]
        node = cur
    return node


def render():
    doc = yaml.safe_load(SPEC.read_text(encoding='utf-8'))
    out = [f"# VR-01 Business API — {doc['info']['version']}", '',
           'File này được **sinh tự động** từ `backend/openapi.v1.yaml` bằng `tools/gen_api_docs.py`. Không sửa tay; '
           'sửa spec rồi chạy lại lệnh sinh.', '']
    for plane, title in (('inference', 'Inference plane (cổng 8443)'), ('management', 'Management plane (cổng 9443)')):
        out += [f'## {title}', '', '| Method | Path | operationId | Vai trò | Mô tả | Mã trả về |', '|---|---|---|---|---|---|']
        for path, item in doc['paths'].items():
            for method, op in item.items():
                if method not in ('get', 'post'):
                    continue
                planes = op.get('x-plane')
                planes = planes if isinstance(planes, list) else [planes]
                if plane not in planes and not (planes == ['both'] or planes == [None]):
                    continue
                codes = ', '.join(sorted(op['responses']))
                out.append(f"| {method.upper()} | `{path}` | `{op['operationId']}` | {', '.join(op.get('x-roles', []))} | "
                           f"{op.get('summary', '').replace('|', '/')} | {codes} |")
        out.append('')
    out += ['## Giới hạn và timeout (`info.x-limits`, giá trị đề xuất)', '', '| Tên | Giá trị |', '|---|---|']
    out += [f'| `{k}` | {v} |' for k, v in doc['info'].get('x-limits', {}).items()]
    schemas = doc['components']['schemas']
    out += ['', '## Trạng thái, kết luận, lý do kỹ thuật', '',
            f"- Trạng thái: {', '.join(f'`{x}`' for x in schemas['State']['enum'])}",
            f"- Kết luận (chỉ khi `COMPLETED`): {', '.join(f'`{x}`' for x in schemas['Decision']['enum'] if x)}",
            f"- Lý do kỹ thuật: {', '.join(f'`{x}`' for x in schemas['TechnicalReason']['enum'] if x)}",
            '', '## Mã lỗi (`code` trong `application/problem+json`)', '',
            ', '.join(f'`{x}`' for x in schemas['ErrorCode']['enum']), '',
            '## Trường của request gửi ảnh (`InspectionSubmit`)', '', '| Trường | Bắt buộc | Kiểu / ràng buộc |', '|---|---|---|']
    sub = schemas['InspectionSubmit']
    for name, prop in sub['properties'].items():
        p = resolve(doc, prop)
        desc = p.get('type', 'object')
        extra = [f"{k}={p[k]}" for k in ('pattern', 'minLength', 'maxLength', 'format', 'enum') if k in p]
        out.append(f"| `{name}` | {'có' if name in sub['required'] else 'không'} | {desc} {' '.join(map(str, extra))} |".replace(' |', ' |'))
    return '\n'.join(out) + '\n'


def main():
    text = render()
    if '--check' in sys.argv:
        ok = OUT.is_file() and OUT.read_text(encoding='utf-8') == text
        print('API.md up to date' if ok else 'API.md is STALE: run tools/gen_api_docs.py')
        return 0 if ok else 1
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding='utf-8')
    print(f'wrote {OUT} ({len(text.splitlines())} lines)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
