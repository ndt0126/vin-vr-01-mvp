#!/bin/bash
# Dong goi ket qua phien W5 vao /tmp/w5-pack (khong token/khoa/anh) + MANIFEST. Chay tren VPS trong mvp/.
set -uo pipefail
cd "$(dirname "$0")/.."
W=run/w5
python3 - <<'PY'
import json, pathlib
toks = [v['token'].encode() for v in json.load(open('run/auth/lab-tokens.secret.json')).values()]
hits = [str(p) for p in pathlib.Path('run').rglob('*') if p.is_file() and '/auth/' not in str(p)
        and p.stat().st_size < 200_000_000 and any(t in p.read_bytes() for t in toks)]
pathlib.Path('run/w5/token-leak-scan.txt').write_text('token leaks outside auth/: %s\n' % hits)
PY
# Goi ket qua: khong lay token, private key, anh, ledger tho; co MANIFEST de doi chieu sau khi keo ve
rm -rf /tmp/w5-pack && mkdir -p /tmp/w5-pack
rsync -a --exclude auth --exclude '*.key' --exclude images --exclude 'data.*' --exclude backup --exclude 'ledger.sqlite3-*' \
  --exclude diag --exclude '*.onnx' --exclude triton-repo --exclude examples run/ /tmp/w5-pack/run/
cp run/diag/*.tar.gz /tmp/w5-pack/ 2>/dev/null
( cd /tmp/w5-pack && find . -type f ! -name MANIFEST.sha256 | sort | xargs sha256sum > MANIFEST.sha256 )
chmod -R a+rX /tmp/w5-pack
( cd /tmp/w5-pack && find . -type f ! -name MANIFEST.sha256 | sort | xargs sha256sum > MANIFEST.sha256 )
