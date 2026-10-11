#!/bin/bash
# Cai lop ung dung MVP tu GOI OFFLINE len node da co Kubernetes. Khong dung Internet. CHUA CHAY THU.
# Usage: <bundle>/mvp/deploy/k8s/install_offline.sh <bundle dir>
set -euo pipefail
B="$(cd "${1:?bundle dir}" && pwd)"; OVERLAY="${OVERLAY:-offline-cpu}"; RUN="${RUN:-/var/lib/vr01/run}"
cd "$B"
echo "[1/4] kiem toan ven goi"
sha256sum -c --quiet SHA256SUMS
if [ -f SHA256SUMS.asc ] && command -v gpg >/dev/null; then gpg --verify SHA256SUMS.asc SHA256SUMS; else echo "CANH BAO: goi CHUA KY (khong co SHA256SUMS.asc) - chi dung cho lab"; fi
echo "[2/4] nap image vao containerd"
for t in "$B"/images/*.tar; do ctr -n k8s.io images import - < "$t" >/dev/null; done
ctr -n k8s.io images ls -q | grep -E "vr01-mvp-api|vr01-local/tritonserver"
echo "[3/4] trien khai"
kubectl apply -k "$B/mvp/deploy/k8s/overlays/$OVERLAY"
kubectl -n vr01 rollout status deploy/vr01-inspection --timeout=300s
echo "[4/4] kiem tra"
cd mvp && for _ in $(seq 1 60); do python3 tools/vr01ctl.py --run-dir "$RUN" --inference-port 30443 --management-port 30943 status && break; sleep 2; done
