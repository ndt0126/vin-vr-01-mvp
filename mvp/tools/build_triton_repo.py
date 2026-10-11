"""Tao Triton model repository tu cac ModelPackage trong mvp/packages/examples/packages (W3-02).

Moi package (da qua validator W2-05: schema, checksum, I/O, golden) duoc chuyen thanh:
    <out>/<ten model>/1/model.onnx     ONNX opset 13: IMAGE FP32 [1,1,2,2] -> SCORE FP32 [1]
    <out>/<ten model>/config.pbtxt     backend onnxruntime, max_batch_size 0, KIND_CPU hoac KIND_GPU
    <out>/REPO-MANIFEST.json           ten/version/digest package + SHA-256 tung file sinh ra

Package sai (checksum, I/O, backend, golden) bi tu choi kem ly do va KHONG co mat trong repository.
File ONNX duoc ghi truc tiep bang protobuf wire format nen khong can cai goi `onnx`.
Neu may co `onnxruntime`, golden input cua package duoc chay qua file ONNX vua tao va so voi expected_score.

Usage: python3 build_triton_repo.py --out ../run/triton-repo [--packages DIR] [--instance-kind KIND_CPU]
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGES_ROOT = HERE.parent / 'packages'
sys.path.insert(0, str(PACKAGES_ROOT))
import validate_design  # noqa: E402

FLOAT, INT64 = 1, 7


# ---------------------------------------------------------------- minimal protobuf writer


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num, wire, payload):
    return _varint((num << 3) | wire) + payload


def _int(num, value):
    return _field(num, 0, _varint(value))


def _bytes(num, value):
    value = value.encode() if isinstance(value, str) else value
    return _field(num, 2, _varint(len(value)) + value)


def _tensor(name, dims, values):
    body = b''.join(_int(1, d) for d in dims) + _int(2, FLOAT) + _bytes(8, name)
    return body + _bytes(9, struct.pack(f'<{len(values)}f', *values))


def _value_info(name, dims):
    shape = b''.join(_bytes(1, _int(1, d)) for d in dims)
    tensor_type = _int(1, FLOAT) + _bytes(2, shape)
    return _bytes(1, name) + _bytes(2, _bytes(1, tensor_type))


def _node(op, inputs, outputs, attrs=b''):
    return b''.join(_bytes(1, i) for i in inputs) + b''.join(_bytes(2, o) for o in outputs) + \
        _bytes(3, f'{op}_{outputs[0]}') + _bytes(4, op) + attrs


def _attr_ints(name, values):
    return _bytes(5, _bytes(1, name) + b''.join(_int(8, v) for v in values) + _int(20, INT64))


def _attr_int(name, value):
    return _bytes(5, _bytes(1, name) + _int(3, value) + _int(20, 2))


def _attr_tensor(name, tensor_bytes):
    return _bytes(5, _bytes(1, name) + _bytes(5, tensor_bytes) + _int(20, 4))


def _int64_tensor(name, values):
    return b''.join(_int(1, d) for d in [len(values)]) + _int(2, INT64) + _bytes(8, name) + \
        _bytes(9, struct.pack(f'<{len(values)}q', *values))


def _burn_nodes(n, rounds):
    """Lam cham CO CHU DICH cho model fixture: X = mean * Ones(n,n); lap X = X @ (Ones/n). Gia tri khong doi
    Moi vong ton ~n^3 phep nhan tren CPU/GPU; ket qua vong lap khong anh huong SCORE."""
    one = b''.join(_int(1, d) for d in [1]) + _int(2, FLOAT) + _bytes(9, struct.pack('<f', 1.0))
    inv = b''.join(_int(1, d) for d in [1]) + _int(2, FLOAT) + _bytes(9, struct.pack('<f', 1.0 / n))
    nodes = [_node('ConstantOfShape', ['burn_shape'], ['burn_ones'], _attr_tensor('value', one)),
             _node('ConstantOfShape', ['burn_shape'], ['burn_p'], _attr_tensor('value', inv)),
             _node('Mul', ['mean0', 'burn_ones'], ['burn_0'])]
    for i in range(rounds):
        nodes.append(_node('MatMul', [f'burn_{i}', 'burn_p'], [f'burn_{i + 1}']))
    # Ket qua vong lap duoc nhan 0 roi cong vao: SCORE giu DUNG TUYET DOI cong thuc goc, khong bi sai so tich luy.
    nodes.append(_node('ReduceMean', [f'burn_{rounds}'], ['burn_mean'], _attr_ints('axes', [0, 1]) + _attr_int('keepdims', 0)))
    nodes.append(_node('Mul', ['burn_mean', 'burn_zero'], ['burn_nothing']))
    nodes.append(_node('Add', ['mean0', 'burn_nothing'], ['mean_1']))
    return nodes, [_bytes(5, _int64_tensor('burn_shape', [n, n])), _bytes(5, _tensor('burn_zero', [], [0.0]))]


def _fail_nodes(threshold):
    """Fixture 'model hong': suy luan LOI khi mean(IMAGE) >= threshold, dung khi nho hon (golden van dat).
    Cach lam: Reshape gia tri mean (1 phan tu) sang kich thuoc 1 + floor(mean/threshold); >= nguong thi kich thuoc
    la 2 va onnxruntime bao loi luc chay."""
    scale = b''.join(_int(1, d) for d in [1]) + _int(2, FLOAT) + _bytes(8, 'fail_scale') + _bytes(9, struct.pack('<f', 1.0 / threshold))
    one = b''.join(_int(1, d) for d in [1]) + _int(2, FLOAT) + _bytes(8, 'fail_one') + _bytes(9, struct.pack('<f', 1.0))
    nodes = [_node('Mul', ['mean0', 'fail_scale'], ['fail_ratio']), _node('Floor', ['fail_ratio'], ['fail_floor']),
             _node('Min', ['fail_floor', 'fail_one'], ['fail_capped']), _node('Add', ['fail_capped', 'fail_one'], ['fail_dim_f']),
             _node('Cast', ['fail_dim_f'], ['fail_dim'], _attr_int('to', INT64)),
             _node('Reshape', ['mean0', 'fail_dim'], ['mean_1'])]
    return nodes, [_bytes(5, scale), _bytes(5, one)]


def linear_score_onnx(gain, bias, burn=None, fail_above_mean=None):
    """SCORE = clip(gain * mean(IMAGE) + bias, 0, 1).  burn / fail_above_mean chi dung cho fixture test."""
    if fail_above_mean:
        extra, extra_init = _fail_nodes(float(fail_above_mean))
        nodes = [_node('ReduceMean', ['IMAGE'], ['mean0'], _attr_ints('axes', [1, 2, 3]) + _attr_int('keepdims', 0))] + extra + [
            _node('Mul', ['mean_1', 'gain'], ['scaled']), _node('Add', ['scaled', 'bias'], ['raw']),
            _node('Clip', ['raw', 'lo', 'hi'], ['SCORE'])]
        graph = b''.join(_bytes(1, x) for x in nodes) + _bytes(2, 'vr01_linear_score_failing') + b''.join(extra_init)
        for name, dims, vals in (('gain', [1], [gain]), ('bias', [1], [bias]), ('lo', [], [0.0]), ('hi', [], [1.0])):
            graph += _bytes(5, _tensor(name, dims, vals))
        graph += _bytes(11, _value_info('IMAGE', [1, 1, 2, 2])) + _bytes(12, _value_info('SCORE', [1]))
        return _int(1, 7) + _bytes(2, 'vr01-mvp') + _bytes(7, graph) + _bytes(8, _bytes(1, '') + _int(2, 13))
    if burn:
        extra, extra_init = _burn_nodes(int(burn['n']), int(burn['rounds']))
        head = [_node('ReduceMean', ['IMAGE'], ['mean0'], _attr_ints('axes', [1, 2, 3]) + _attr_int('keepdims', 0))]
        nodes = head + extra + [_node('Mul', ['mean_1', 'gain'], ['scaled']), _node('Add', ['scaled', 'bias'], ['raw']),
                                _node('Clip', ['raw', 'lo', 'hi'], ['SCORE'])]
        graph = b''.join(_bytes(1, x) for x in nodes) + _bytes(2, 'vr01_linear_score_slow') + b''.join(extra_init)
        for name, dims, vals in (('gain', [1], [gain]), ('bias', [1], [bias]), ('lo', [], [0.0]), ('hi', [], [1.0])):
            graph += _bytes(5, _tensor(name, dims, vals))
        graph += _bytes(11, _value_info('IMAGE', [1, 1, 2, 2])) + _bytes(12, _value_info('SCORE', [1]))
        return _int(1, 7) + _bytes(2, 'vr01-mvp') + _bytes(7, graph) + _bytes(8, _bytes(1, '') + _int(2, 13))
    nodes = [
        _node('ReduceMean', ['IMAGE'], ['mean'], _attr_ints('axes', [1, 2, 3]) + _attr_int('keepdims', 0)),
        _node('Mul', ['mean', 'gain'], ['scaled']),
        _node('Add', ['scaled', 'bias'], ['raw']),
        _node('Clip', ['raw', 'lo', 'hi'], ['SCORE']),
    ]
    graph = b''.join(_bytes(1, n) for n in nodes) + _bytes(2, 'vr01_linear_score')
    for name, dims, vals in (('gain', [1], [gain]), ('bias', [1], [bias]), ('lo', [], [0.0]), ('hi', [], [1.0])):
        graph += _bytes(5, _tensor(name, dims, vals))
    graph += _bytes(11, _value_info('IMAGE', [1, 1, 2, 2])) + _bytes(12, _value_info('SCORE', [1]))
    opset = _bytes(1, '') + _int(2, 13)
    return _int(1, 7) + _bytes(2, 'vr01-mvp') + _bytes(7, graph) + _bytes(8, opset)


def config_pbtxt(name, kind):
    return f'''name: "{name}"
backend: "onnxruntime"
max_batch_size: 0
input [ {{ name: "IMAGE", data_type: TYPE_FP32, dims: [ 1, 1, 2, 2 ] }} ]
output [ {{ name: "SCORE", data_type: TYPE_FP32, dims: [ 1 ] }} ]
instance_group [ {{ count: 1, kind: {kind} }} ]
'''


def run_golden(onnx_bytes, golden_input):
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError:
        return None
    sess = ort.InferenceSession(onnx_bytes, providers=['CPUExecutionProvider'])
    x = np.asarray(golden_input, dtype=np.float32).reshape(1, 1, 2, 2)
    return float(sess.run(['SCORE'], {'IMAGE': x})[0][0])


def build(packages_dir, out_dir, kind='KIND_CPU', config=None):
    """Tra ve (accepted, rejected). Chi package hop le moi duoc ghi vao out_dir."""
    packages_dir, out_dir = Path(packages_dir), Path(out_dir)
    config = config or validate_design.parse(validate_design.read(packages_dir.parent / 'site-config.json'))
    final_dir, out_dir = out_dir, out_dir.parent / f'.{out_dir.name}.building'
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    accepted, rejected = [], []
    for manifest in sorted(packages_dir.glob('*/manifest.json')):
        try:
            pkg, digest, _ = validate_design.validate_package(manifest, config)
            params = json.loads((manifest.parent / pkg['artifact']['path']).read_bytes())
            burn_file = manifest.parent / 'triton-build.json'  # chi fixture test moi co file nay
            build_cfg = json.loads(burn_file.read_text()) if burn_file.is_file() else {}
            burn, fail_above = build_cfg.get('burn'), build_cfg.get('fail_above_mean')
            if burn and os.environ.get('VR01_SLOW_ROUNDS'):  # hieu chinh do cham theo may dang chay
                burn = dict(burn, rounds=int(os.environ['VR01_SLOW_ROUNDS']))
            onnx_bytes = linear_score_onnx(float(params['gain']), float(params['bias']), burn, fail_above)
            golden_in = json.loads((manifest.parent / pkg['golden']['input']['path']).read_bytes())
            actual = run_golden(onnx_bytes, golden_in)
            g = pkg['golden']
            # ONNX tinh bang float32, package khai bao bang float64: cho phep them sai so float32.
            tol = max(g['atol'] + g['rtol'] * abs(g['expected_score']), 1e-6)
            if actual is not None and abs(actual - g['expected_score']) > tol:
                raise validate_design.Rejected('E_GOLDEN', f"onnx golden {actual} != {g['expected_score']}")
        except validate_design.Rejected as exc:
            rejected.append({'package': manifest.parent.name, 'code': exc.code, 'reason': str(exc)})
            continue
        mdir = out_dir / pkg['name'] / '1'
        mdir.mkdir(parents=True)
        (mdir / 'model.onnx').write_bytes(onnx_bytes)
        cfg = config_pbtxt(pkg['name'], kind)
        (out_dir / pkg['name'] / 'config.pbtxt').write_text(cfg)
        accepted.append({'name': pkg['name'], 'version': pkg['version'], 'manifest_sha256': digest, 'burn': burn, 'fail_above_mean': fail_above,
                         'instance_kind': kind, 'golden_expected': g['expected_score'], 'golden_onnx': actual,
                         'files': {'1/model.onnx': hashlib.sha256(onnx_bytes).hexdigest(),
                                   'config.pbtxt': hashlib.sha256(cfg.encode()).hexdigest()}})
    manifest = json.dumps({'models': accepted, 'rejected': rejected,
                           'golden_checked_with_onnxruntime': all(m['golden_onnx'] is not None for m in accepted)},
                          indent=2) + '\n'
    (out_dir / 'REPO-MANIFEST.json').write_text(manifest)
    # Khong bao gio xoa chinh thu muc dich: Triton dang chay bind-mount thu muc do, xoa di tao lai thi
    # container van nhin thu muc cu (rong) va bao "model not found". Noi dung khong doi thi khong dung toi.
    final_dir.mkdir(parents=True, exist_ok=True)
    current = final_dir / 'REPO-MANIFEST.json'
    if not (current.is_file() and current.read_text() == manifest):
        for child in final_dir.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        for child in out_dir.iterdir():
            shutil.move(str(child), str(final_dir / child.name))
    shutil.rmtree(out_dir)
    return accepted, rejected


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--packages', type=Path, default=PACKAGES_ROOT / 'examples' / 'packages')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--instance-kind', default='KIND_CPU', choices=['KIND_CPU', 'KIND_GPU'])
    args = ap.parse_args()
    accepted, rejected = build(args.packages, args.out, args.instance_kind)
    for m in accepted:
        print(f"OK      {m['name']}@{m['version']}  {m['instance_kind']}  golden onnx={m['golden_onnx']}")
    for r in rejected:
        print(f"REJECT  {r['package']}: {r['code']} {r['reason']}")
    return 0 if accepted and not rejected else 1


if __name__ == '__main__':
    sys.exit(main())
