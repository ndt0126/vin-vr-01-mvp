"""Sinh fixture 'model nang': mot mang tich chap sau (Conv3x3 + ReLU) nhan anh RGB va tra mot diem [0,1].

Muc dich: co mot tai GPU THAT (tich chap, VRAM) cho bai hieu nang/stress, dong goi dung chuan ModelPackage
(backend triton-onnx-v1, preprocess image-rgb-unit-v1). Trong so la so gia ngau nhien TAT DINH tu seed, nen cung
tham so thi file model.onnx co cung SHA-256 tren moi may. Day KHONG phai model QC va khong duoc huan luyen.

Usage: python3 tools/make_heavy_fixture.py --examples run/examples [--layers 24 --channels 64 --size 512]
                                           [--device cpu|nvidia-gpu] [--name model-heavy]
Do nang tinh toan ~ layers * channels^2 * size^2. Can onnxruntime de tinh expected_score cua golden.
"""
import argparse
import hashlib
import io
import json
import math
import random
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from build_triton_repo import _attr_int, _attr_ints, _bytes, _int, _node, FLOAT, INT64  # noqa: E402

UINT8 = 2

# Cac muc co san. expected/sha256 tinh bang onnxruntime CPU ngay 11/10/2026; may khong co onnxruntime van sinh duoc
# goi vi model la tat dinh (SHA-256 phai khop) va golden duoc kiem lai boi inference server khi kich hoat.
PRESETS = {
    'tiny': {'layers': 2, 'channels': 4, 'size': 32, 'expected': 0.594379,
             'onnx_sha256': 'fc4e1a3ff80909d3682a7cc81f9ca18223d200b15c463ed3c0aff7d1ce717017'},
    'cpu': {'layers': 16, 'channels': 48, 'size': 192, 'expected': 0.425518,
            'onnx_sha256': 'dd7d7ed85ee9cff2aad57c12bcc5d2713888c52cd069d185dd8f707bd74c42db'},
    'gpu': {'layers': 48, 'channels': 96, 'size': 512, 'expected': 0.472522,
            'onnx_sha256': 'c2dcb69e6074cf72b8d4b134a0c16df0ce6b0c81e69cc0d0b3e0b120049afbb0'},
    'gpu-xl': {'layers': 64, 'channels': 128, 'size': 1024, 'expected': 0.479788,
               'onnx_sha256': '63804825d78a7705f7ece54c30148a83deda2fab2836610e532ebb50197e097a'},
}


def _raw_tensor(name, dims, floats):
    body = b''.join(_int(1, d) for d in dims) + _int(2, FLOAT) + _bytes(8, name)
    return body + _bytes(9, struct.pack(f'<{len(floats)}f', *floats))


def _vi(name, elem, dims):
    shape = b''.join(_bytes(1, _int(1, d)) for d in dims)
    return _bytes(1, name) + _bytes(2, _bytes(1, _int(1, elem) + _bytes(2, shape)))


def conv_score_onnx(layers, channels, size, seed=20261011):
    """IMAGE UINT8 [1,3,S,S] -> Cast -> /255 -> (Conv3x3 + ReLU) x layers -> GlobalAveragePool -> mean -> Sigmoid -> SCORE [1]."""
    rng = random.Random(seed)
    nodes = [_node('Cast', ['IMAGE'], ['img_f'], _attr_int('to', FLOAT)), _node('Mul', ['img_f', 'inv255'], ['x0'])]
    inits = [_bytes(5, _raw_tensor('inv255', [1], [1.0 / 255.0]))]
    cin = 3
    for i in range(layers):
        bound = math.sqrt(6.0 / (cin * 9))  # He-uniform: giu do lon kich hoat on dinh qua nhieu lop ReLU
        w = [rng.uniform(-bound, bound) for _ in range(channels * cin * 9)]
        inits.append(_bytes(5, _raw_tensor(f'w{i}', [channels, cin, 3, 3], w)))
        inits.append(_bytes(5, _raw_tensor(f'b{i}', [channels], [0.01] * channels)))
        nodes.append(_node('Conv', [f'x{i}', f'w{i}', f'b{i}'], [f'c{i}'],
                           _attr_ints('kernel_shape', [3, 3]) + _attr_ints('pads', [1, 1, 1, 1])))
        nodes.append(_node('Relu', [f'c{i}'], [f'x{i + 1}']))
        cin = channels
    inits.append(_bytes(5, _raw_tensor('center', [1], [0.5])))
    one = b''.join(_int(1, d) for d in [1]) + _int(2, INT64) + _bytes(8, 'shape1') + _bytes(9, struct.pack('<q', 1))
    inits.append(_bytes(5, one))
    nodes += [_node('GlobalAveragePool', [f'x{layers}'], ['gap']),
              _node('ReduceMean', ['gap'], ['m'], _attr_ints('axes', [1, 2, 3]) + _attr_int('keepdims', 0)),
              _node('Sub', ['m', 'center'], ['centered']), _node('Sigmoid', ['centered'], ['sig']),
              _node('Reshape', ['sig', 'shape1'], ['SCORE'])]
    graph = b''.join(_bytes(1, n) for n in nodes) + _bytes(2, 'vr01_conv_score') + b''.join(inits)
    graph += _bytes(11, _vi('IMAGE', UINT8, [1, 3, size, size])) + _bytes(12, _vi('SCORE', FLOAT, [1]))
    return _int(1, 7) + _bytes(2, 'vr01-mvp') + _bytes(7, graph) + _bytes(8, _bytes(1, '') + _int(2, 13))


def golden_png(size=64):
    """Anh mau tat dinh (gradient RGB), PNG."""
    from PIL import Image
    im = Image.new('RGB', (size, size))
    im.putdata([((x * 255) // (size - 1), (y * 255) // (size - 1), ((x + y) * 255) // (2 * size - 2))
                for y in range(size) for x in range(size)])
    b = io.BytesIO()
    im.save(b, 'PNG', optimize=False, compress_level=6)
    return b.getvalue()


def rgb_chw_uint8(image_bytes, size):
    """Tien xu ly image-rgb-unit-v1 phia API: RGB, resize bilinear ve size x size, xep CHW, uint8 (chia 255 nam trong model)."""
    from PIL import Image
    with Image.open(io.BytesIO(image_bytes)) as im:
        rgb = im.convert('RGB').resize((size, size), Image.Resampling.BILINEAR)
        return b''.join(ch.tobytes() for ch in rgb.split())


def run_onnx(onnx_bytes, chw_bytes, size):
    import numpy as np
    import onnxruntime as ort
    sess = ort.InferenceSession(onnx_bytes, providers=['CPUExecutionProvider'])
    x = np.frombuffer(chw_bytes, dtype=np.uint8).reshape(1, 3, size, size)
    return float(sess.run(['SCORE'], {'IMAGE': x})[0][0])


def sha(b):
    return hashlib.sha256(b).hexdigest()


def make(examples, name='model-heavy', layers=24, channels=64, size=512, device='cpu', expected=None, seed=20261011):
    examples = Path(examples)
    d = examples / 'packages' / name
    d.mkdir(parents=True, exist_ok=True)
    onnx_bytes = conv_score_onnx(layers, channels, size, seed)
    png = golden_png()
    if expected is None:
        expected = round(run_onnx(onnx_bytes, rgb_chw_uint8(png, size), size), 6)
    (d / 'model.onnx').write_bytes(onnx_bytes)
    (d / 'golden-input.png').write_bytes(png)
    profile = 'triton-onnx-gpu-v1' if device == 'nvidia-gpu' else 'triton-onnx-cpu-v1'
    params = layers * (channels * channels * 9 + channels)
    act_mib = math.ceil(2 * channels * size * size * 4 / 2 ** 20)  # 2 tensor kich hoat song song (uoc luong)
    manifest = {
        'schema_version': 'w2-draft-v1', 'name': name, 'version': '0.1.0', 'purpose': 'fixture',
        'artifact': {'path': 'model.onnx', 'sha256': sha(onnx_bytes)},
        'runtime': {'backend': 'triton-onnx-v1', 'profile': profile, 'device': device},
        'io': {'input': {'name': 'IMAGE', 'dtype': 'UINT8', 'shape': [1, 3, size, size]},
               'output': {'name': 'SCORE', 'dtype': 'FP32', 'shape': [1]}},
        'preprocess': 'image-rgb-unit-v1', 'postprocess': 'normalized-score-v1',
        'resources': {'cpu_millicores': 2000, 'ram_mib': 512 + act_mib + params * 4 // 2 ** 20,
                      'peak_vram_mib': (256 + 2 * act_mib) if device == 'nvidia-gpu' else 0, 'basis': 'estimate'},
        'compatibility': {'platform_contract': 'w2-draft-v1', 'os': 'linux', 'arch': 'amd64'},
        'warmup': {'runs': 1, 'timeout_ms': 60000},
        'golden': {'input': {'path': 'golden-input.png', 'sha256': sha(png)}, 'expected_score': expected,
                   'atol': 0.002, 'rtol': 0.0},
        'rollback_candidates': []}
    raw = json.dumps(manifest, indent=2) + '\n'
    (d / 'manifest.json').write_text(raw)
    ra = (examples / 'recipes' / 'recipe-a.json').read_bytes()
    recipe = {'schema_version': 'w2-draft-v1', 'name': name.replace('model-', 'recipe-'), 'version': '0.1.0',
              'site_id': 'lab-only', 'station_id': 'station-sim',
              'package': {'name': name, 'version': '0.1.0', 'manifest_sha256': sha(raw.encode())},
              'decision': {'rule': 'score-gte-threshold-is-ng', 'threshold': 0.5},
              'rollback_recipe': {'name': 'recipe-a', 'version': '0.1.0', 'sha256': sha(ra)}}
    (examples / 'recipes' / f"{recipe['name']}.json").write_text(json.dumps(recipe, indent=2) + '\n')
    # May phai cho phep loai package nay: cap nhat site-config trong THU MUC CHAY (ban goc trong packages/ khong doi).
    cfg_path = examples / 'site-config.json'
    cfg = json.loads(cfg_path.read_text())
    if 'image-rgb-unit-v1' not in cfg['policy']['allowed_preprocess']:
        cfg['policy']['allowed_preprocess'].append('image-rgb-unit-v1')
    if not any(p['name'] == profile for p in cfg['runtime_profiles']):
        cfg['runtime_profiles'].append({'name': profile, 'backend': 'triton-onnx-v1', 'device': device, 'image_digest': None})
    cfg['limits']['max_decoded_pixels'] = max(cfg['limits']['max_decoded_pixels'], size * size)
    res = manifest['resources']
    cfg['capacity']['cpu_millicores'] = max(cfg['capacity']['cpu_millicores'], res['cpu_millicores'])
    cfg['capacity']['ram_mib'] = max(cfg['capacity']['ram_mib'], res['ram_mib'])
    if device == 'nvidia-gpu':
        cfg['capacity']['available_vram_mib'] = max(cfg['capacity']['available_vram_mib'], res['peak_vram_mib'] + 1024)
        cfg['capacity']['gpu_reserve_mib'] = max(cfg['capacity']['gpu_reserve_mib'], 900)
    cfg_path.write_text(json.dumps(cfg, indent=2) + '\n')
    return {'name': name, 'layers': layers, 'channels': channels, 'size': size, 'device': device,
            'onnx_bytes': len(onnx_bytes), 'onnx_sha256': sha(onnx_bytes), 'parameters': params, 'golden_expected': expected}


# Model nang THU HAI (cung kien truc, seed khac -> trong so va diem khac): de bai chuyen model dung hai model that.
SEED_B = 20261012
PRESETS_B = {
    "tiny": {
        "expected": 0.55614,
        "onnx_sha256": "d89ca68cb871b1ed68447a2efa508308a20081b715abb59f028cdcfc2a2e7b2f"
    },
    "cpu": {
        "expected": 0.563869,
        "onnx_sha256": "aeaed305ea9cb3d5c705365de323185d65317838ca44c79f9f4d0222212afde7"
    },
    "gpu": {
        "expected": 0.426981,
        "onnx_sha256": "d2d3d3f3fca2625e44e8e376717c77a9c8ce2cb8dad684693895ce08ae8667f6"
    },
    "gpu-xl": {
        "expected": 0.443069,
        "onnx_sha256": "f7de9fc2d4ec90b7a2085729c77675e3e25bae4c6662d69f29904fc1f4b508d9"
    }
}


def make_preset(examples, preset, device='cpu', name='model-heavy'):
    p = dict(PRESETS[preset], **(PRESETS_B[preset] if name.endswith('-b') else {}))
    info = make(examples, name, p['layers'], p['channels'], p['size'], device, p['expected'],
                SEED_B if name.endswith('-b') else 20261011)
    if info['onnx_sha256'] != p['onnx_sha256']:
        raise SystemExit(f"generated model differs from the pinned SHA-256 for preset {preset}: {info['onnx_sha256']}")
    return dict(info, preset=preset)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--examples', type=Path, required=True)
    ap.add_argument('--name', default='model-heavy')
    ap.add_argument('--preset', choices=sorted(PRESETS), help='muc co san (expected + SHA-256 da ghim)')
    ap.add_argument('--layers', type=int, default=24)
    ap.add_argument('--channels', type=int, default=64)
    ap.add_argument('--size', type=int, default=512)
    ap.add_argument('--device', default='cpu', choices=['cpu', 'nvidia-gpu'])
    ap.add_argument('--expected-score', type=float, help='dung khi may khong co onnxruntime (lay tu lan sinh truoc cung tham so)')
    a = ap.parse_args()
    print(json.dumps(make_preset(a.examples, a.preset, a.device, a.name) if a.preset else
                     make(a.examples, a.name, a.layers, a.channels, a.size, a.device, a.expected_score)))


if __name__ == '__main__':
    main()
