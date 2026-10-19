#!/bin/bash
# Dua image vao containerd cua node (khong can registry). Chay trong thu muc mvp/. Usage: deploy/k8s/load-images.sh [tag]
# Day cung la duong cho may khong co Internet: `docker save` thanh file tar o may co mang, chep sang, `ctr images import`.
set -euo pipefail
TAG="${1:-0.5.0-rc2}"
TRITON="nvcr.io/nvidia/tritonserver@sha256:f836551575df7c9fb71144073845c6b3911de57db91a8c95e0687a4d2ac9f7a5"
docker build -q -t "vr01-mvp-api:${TAG}" -f deploy/Dockerfile . >/dev/null
docker save "vr01-mvp-api:${TAG}" | ctr -n k8s.io images import - >/dev/null
# Triton: keo thang bang containerd theo digest (lab co mang). May offline: docker save/ctr import nhu tren.
ctr -n k8s.io images pull "$TRITON" >/dev/null
ctr -n k8s.io images ls -q | grep -E "vr01-mvp-api:${TAG}|tritonserver@" 
