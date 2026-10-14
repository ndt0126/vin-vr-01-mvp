#!/bin/bash
# Phien Tuan 5 tren VPS (W5-02 UI E2E + W5-04 UAT tu dong + W5-05 smoke tu ban release). Chay tren VPS bang root,
# trong thu muc mvp/ cua ban clone, TACH khoi SSH (nohup). Khong tu terminate. Khi xong ghi run/w5/DONE.
# Usage (do tools/run_w5_session.sh goi): nohup tools/w5_remote.sh > run/w5/remote.log 2>&1 &
set -uo pipefail
cd "$(dirname "$0")/.."
W=run/w5; mkdir -p "$W"; rm -f "$W/DONE"; : > "$W/steps.txt"
step() {  # step <ten> <lenh...>: ghi log rieng, ma thoat va thoi gian vao steps.txt; khong dung khi loi
  local name="$1"; shift; local t0=$(date +%s)
  echo "[$(date -u +%H:%M:%S)] >>> $name" | tee -a "$W/progress.log"
  "$@" > "$W/$name.log" 2>&1; local rc=$?
  printf '%s rc=%s seconds=%s\n' "$name" "$rc" "$(( $(date +%s) - t0 ))" | tee -a "$W/steps.txt" "$W/progress.log"
  return 0
}
{ git rev-parse HEAD; git describe --tags --always 2>/dev/null; } > "$W/git-commit.txt"
{ lsb_release -ds; uname -rm; nproc; free -m | sed -n 2p; df -h / | tail -1
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || echo 'no GPU'
  docker --version; docker compose version --short; node --version; grep -E '^(MVP_VERSION|TRITON_INSTANCE_KIND|VR01_GPU)=' deploy/.env; } > "$W/host-info.txt" 2>&1

step 01-start make start SLOW=1 HEAVY=gpu
step 02-status python3 tools/vr01ctl.py --run-dir run status
step 03-smoke make smoke
step 04-e2e-setup make e2e-setup
step 05-e2e make e2e
rm -rf "$W/e2e"; rm -rf "$W/e2e"; cp -r run/e2e "$W/e2e" 2>/dev/null
# UAT tu dong theo checklist W5-04: phase main (P0-P12, P14), w4 (P13-P18, can Prometheus/Grafana)
step 06-uat-main python3 -B tests/real_session.py --phase main
step 08-obs-start make obs-start
step 09-uat-w4 python3 -B tests/real_session.py --phase w4
step 10-make-test make test
step 11-e2e-again make e2e   # UI van dung sau moi su co/nang cap o tren
rm -rf "$W/e2e-again"; rm -rf "$W/e2e-again"; cp -r run/e2e "$W/e2e-again" 2>/dev/null
step 12-status-final python3 tools/vr01ctl.py --run-dir run status
step 13-diag make diag
docker logs vr01-mvp-triton-1 > "$W/triton.log" 2>&1; docker logs vr01-mvp-api-1 > "$W/api.log" 2>&1
nvidia-smi > "$W/nvidia-smi.txt" 2>&1
date -u +%FT%TZ > "$W/DONE"; tools/w5_pack.sh
echo "W5 REMOTE DONE"
