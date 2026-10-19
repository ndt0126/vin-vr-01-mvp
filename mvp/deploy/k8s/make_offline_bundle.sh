#!/bin/bash
# Tao GOI OFFLINE cho lop UNG DUNG cua MVP (2 image + manifests + cong cu), tren may CO Internet da chay load-images.sh.
# Usage (trong mvp/): deploy/k8s/make_offline_bundle.sh /root/vr01-app-bundle [tag]
# Goi KHONG gom Kubernetes/containerd/driver (lop nen offline cua du an la bo r4.x). CHUA CHAY THU.
set -euo pipefail
OUT="${1:?thu muc dich}"; TAG="${2:-0.5.0-rc2}"
# Bien moi truong (chi doi khi thu tren may dev): TRITON_SRC, PLATFORM.
TRITON_SRC="${TRITON_SRC:-nvcr.io/nvidia/tritonserver@sha256:f836551575df7c9fb71144073845c6b3911de57db91a8c95e0687a4d2ac9f7a5}"; PLATFORM="${PLATFORM:-linux/amd64}"
TRITON_LOCAL="vr01-local/tritonserver:2.60.0-25.08"
FINAL="$OUT"; OUT="${FINAL}.building"   # dung goi o thu muc tam; chi thay goi cu khi goi moi hoan chinh
rm -rf "$OUT"; mkdir -p "$OUT/images" "$OUT/mvp"
# Nguon image Triton: uu tien ref theo digest; neu node da duoc cai tu goi thi chi con tag local -> dung tag do.
if ctr -n k8s.io images ls -q | grep -qF "$TRITON_SRC"; then ctr -n k8s.io images tag --force "$TRITON_SRC" "docker.io/$TRITON_LOCAL" >/dev/null
elif ! ctr -n k8s.io images ls -q | grep -qF "docker.io/$TRITON_LOCAL"; then echo "khong tim thay image Triton tren node ($TRITON_SRC hoac $TRITON_LOCAL)"; exit 1; fi
ctr -n k8s.io images export --platform "$PLATFORM" - "docker.io/$TRITON_LOCAL" > "$OUT/images/tritonserver.tar"
ctr -n k8s.io images export --platform "$PLATFORM" - "docker.io/library/vr01-mvp-api:${TAG}" > "$OUT/images/vr01-mvp-api.tar"
for d in deploy/k8s tools tests packages backend docs; do mkdir -p "$OUT/mvp/$(dirname $d)"; cp -R "$d" "$OUT/mvp/$d"; done
for t in "$OUT"/images/*.tar; do tar tf "$t" >/dev/null || { echo "image tar hong: $t"; exit 1; }; done
find "$OUT/mvp" -name __pycache__ -prune -exec rm -rf {} +
cat > "$OUT/BUNDLE-INFO.txt" <<INFO
VR-01 MVP app bundle (LAB, UNSIGNED unless SHA256SUMS.asc is present)
created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
source_commit=$(git -C .. rev-parse HEAD 2>/dev/null || echo unknown)
api_image=vr01-mvp-api:${TAG}
triton_image=${TRITON_LOCAL}  (from ${TRITON_SRC})
scope=application layer only; Kubernetes/containerd/driver are NOT included
INFO
( cd "$OUT" && find . -type f ! -name SHA256SUMS ! -name SHA256SUMS.asc | sort | xargs sha256sum > SHA256SUMS )
rm -rf "$FINAL"; mv "$OUT" "$FINAL"; OUT="$FINAL"
du -sh "$OUT" | cut -f1; wc -l < "$OUT/SHA256SUMS"
