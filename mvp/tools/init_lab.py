"""Khoi tao du lieu LAB cho MVP trong mot thu muc run/ (chay lai duoc, khong ghi de thu da co):
  auth/principals.json        SHA-256 cua token (server doc)
  auth/lab-tokens.secret.json token lab, mode 600 - KHONG dua vao evidence/repo
  tls/ca.crt, server.crt/key  CA lab + chung chi server (SAN localhost, 127.0.0.1, api)
  triton-repo/                model repository sinh tu ModelPackage (luon tao lai)
Day la khoa/chung chi THU NGHIEM. Production dung PKI nha may (chua lam).
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'backend'))
sys.path.insert(0, str(HERE))
import build_triton_repo  # noqa: E402
import inspection_api  # noqa: E402

EXT = '''basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=serverAuth
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid
subjectAltName=DNS:localhost,DNS:api,IP:127.0.0.1
'''


def make_tls(d):
    d.mkdir(parents=True, exist_ok=True)
    if not shutil.which('openssl'):
        raise SystemExit('openssl is required to create the lab certificate')

    def run(*a):
        subprocess.run(a, cwd=d, check=True, capture_output=True)

    run('openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
        '-keyout', 'ca.key', '-out', 'ca.crt', '-days', '30', '-subj', '/CN=VR01 MVP LAB CA',
        '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    run('openssl', 'req', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
        '-keyout', 'server.key', '-out', 'server.csr', '-subj', '/CN=localhost')
    (d / 'server.ext').write_text(EXT)
    run('openssl', 'x509', '-req', '-in', 'server.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key', '-CAcreateserial',
        '-out', 'server.crt', '-days', '30', '-extfile', 'server.ext')
    run('openssl', 'verify', '-x509_strict', '-CAfile', 'ca.crt', 'server.crt')
    for name in ('ca.key', 'server.key'):
        os.chmod(d / name, 0o600)
    for name in ('server.csr', 'server.ext', 'ca.srl'):
        (d / name).unlink(missing_ok=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-dir', type=Path, required=True)
    ap.add_argument('--instance-kind', default='KIND_CPU', choices=['KIND_CPU', 'KIND_GPU'])
    ap.add_argument('--with-heavy-fixture', choices=['tiny', 'cpu', 'gpu', 'gpu-xl'],
                    help='them model-heavy/recipe-heavy: mang tich chap that (backend triton-onnx-v1) o muc da chon')
    ap.add_argument('--with-slow-fixture', action='store_true',
                    help='them fixture test: model-slow (timeout/cancel/drain) va model-bad (tu rollback)')
    ap.add_argument('--reset-fixtures', action='store_true', help='bo cac fixture test da chon o lan chay truoc')
    args = ap.parse_args()
    run = args.run_dir
    # Lua chon fixture duoc NHO lai trong run/init-options.json: `make start` ve sau khong lam mat model dang dung.
    opt_file = run / 'init-options.json'
    if not args.reset_fixtures and opt_file.is_file():
        # Gop tung lua chon: co chi dinh thi dung gia tri moi, khong chi dinh thi giu lua chon cu.
        # (Ban dau chi giu khi KHONG co co nao -> `make start SLOW=1` lam mat model-heavy; lo ra o phien VPS 11/10.)
        saved = json.loads(opt_file.read_text())
        args.with_slow_fixture = args.with_slow_fixture or saved.get('slow', False)
        args.with_heavy_fixture = args.with_heavy_fixture or saved.get('heavy')
    (run / 'data').mkdir(parents=True, exist_ok=True)
    if (run / 'auth' / 'principals.json').is_file():
        print('auth: kept existing lab principals')
    else:
        inspection_api.init_lab_principals(run / 'auth')
        print('auth: created lab principals (token file mode 600)')
    if (run / 'tls' / 'server.crt').is_file():
        print('tls: kept existing lab certificate')
    else:
        make_tls(run / 'tls')
        print('tls: created lab CA + server certificate (30 days, strict X.509 verified)')
    # Kho package/recipe ma API doc luc chay: ban sao cua packages/examples (+ fixture cham neu duoc yeu cau).
    examples = run / 'examples'
    if examples.exists():
        shutil.rmtree(examples)
    shutil.copytree(build_triton_repo.PACKAGES_ROOT / 'examples', examples)
    if args.with_slow_fixture:
        for fixture in ('slow', 'bad'):
            for part in ('packages', 'recipes'):
                shutil.copytree(HERE.parent / 'tests' / 'fixtures' / fixture / part, examples / part, dirs_exist_ok=True)
        print('examples: added TEST FIXTURES model-slow / recipe-slow, model-bad / recipe-bad')
    if args.with_heavy_fixture:
        import make_heavy_fixture
        dev = 'nvidia-gpu' if args.instance_kind == 'KIND_GPU' else 'cpu'
        info = make_heavy_fixture.make_preset(examples, args.with_heavy_fixture, dev)
        make_heavy_fixture.make_preset(examples, args.with_heavy_fixture, dev, 'model-heavy-b')
        print(f"examples: added TEST FIXTURES model-heavy + model-heavy-b ({info['preset']}: {info['layers']} lop, {info['channels']} kenh, "
              f"anh {info['size']}x{info['size']}, {info['onnx_bytes'] // 1024} KiB, device {info['device']})")
    accepted, rejected = build_triton_repo.build(examples / 'packages', run / 'triton-repo', args.instance_kind)
    opt_file.write_text(json.dumps({'slow': bool(args.with_slow_fixture), 'heavy': args.with_heavy_fixture}))
    for m in accepted:
        print(f"model: {m['name']}@{m['version']} {m['instance_kind']} digest {m['manifest_sha256'][:12]}")
    for r in rejected:
        print(f"model REJECTED: {r['package']} {r['code']}")
    return 0 if accepted and not rejected else 1


if __name__ == '__main__':
    sys.exit(main())
