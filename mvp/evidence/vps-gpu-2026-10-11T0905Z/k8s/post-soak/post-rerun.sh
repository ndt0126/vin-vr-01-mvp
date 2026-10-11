#!/bin/bash
# Chay lai TAY phan offline tren node GPU sau khi sua swap (lan tu dong hong vi kubelet khong len sau reboot).
cd /opt/vin-vr-01-mvp/mvp; E=/root/k8s-evidence/post-soak; B=/root/vr01-app-bundle; R=$E/offline-rerun-report.txt; : > $R
step(){ echo "$2  $1  $3" | tee -a $R; }
probe(){ for u in https://nvcr.io https://registry-1.docker.io https://github.com http://1.1.1.1; do for v in -4 -6; do curl $v -s -m 4 -o /dev/null "$u" && { echo "open($v $u)"; return; }; done; done; echo blocked; }
while ps -eo args | grep -qE '^python3 -B tests/triton_direct_sweep'; do sleep 5; done
make down >/dev/null 2>&1
kubectl delete namespace vr01 --ignore-not-found --wait=true >/dev/null 2>&1; kubectl delete pv vr01-run --ignore-not-found >/dev/null 2>&1
for i in $(seq 1 60); do [ "$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}')" = 1 ] && break; sleep 5; done
step "R0 node Ready with 1 allocatable GPU after swap fix" $([ "$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}')" = 1 ] && echo PASS || echo FAIL) ""
P=$(probe); step "R1 Internet egress cut (IPv4 + IPv6)" $([ "$P" = blocked ] && echo PASS || echo FAIL) "probe=$P"
LEFT=$(ctr -n k8s.io images ls -q | grep -c -E "tritonserver|vr01-mvp-api"); step "R2 app images absent before install" $([ "$LEFT" = 0 ] && echo PASS || echo FAIL) "left=$LEFT"
T0=$(date +%s); OVERLAY=offline-gpu bash $B/mvp/deploy/k8s/install_offline.sh $B > $E/offline-install-rerun.log 2>&1; rc=$?
step "R3 install from the bundle (overlay offline-gpu) with egress cut" $([ $rc = 0 ] && echo PASS || echo FAIL) "$(( $(date +%s)-T0 ))s; $(tail -1 $E/offline-install-rerun.log | cut -c1-80)"
for _ in $(seq 1 120); do [ "$(curl -sk -m 3 -o /dev/null -w '%{http_code}' https://127.0.0.1:30943/readyz)" = 200 ] && break; sleep 2; done
(cd $B/mvp && python3 tests/smoke.py --run-dir /var/lib/vr01/run --inference-port 30443 --management-port 30943 --output $E/offline-smoke-rerun.json) > $E/offline-smoke-rerun.log 2>&1
step "R4 smoke flow on the offline-installed GPU stack" $([ $? = 0 ] && echo PASS || echo FAIL) "$(tail -1 $E/offline-smoke-rerun.log | cut -c1-40)"
PULLS=$(kubectl -n vr01 get events 2>/dev/null | grep -c -E "Pulling image|ErrImagePull|ImagePullBackOff"); step "R5 no image pull attempted" $([ "$PULLS" = 0 ] && echo PASS || echo FAIL) "pull events=$PULLS"
LIM=$(kubectl -n vr01 get pod -l app.kubernetes.io/name=vr01-inspection -o jsonpath='{.items[0].spec.containers[0].resources.limits.nvidia\.com/gpu}'); APPS=$(nvidia-smi --query-compute-apps=process_name,used_memory --format=csv,noheader | tr '\n' ';')
step "R6 Triton pod holds 1 GPU and runs on it" $([ "$LIM" = 1 ] && echo "$APPS" | grep -q tritonserver && echo PASS || echo FAIL) "limit=$LIM apps=$APPS kinds=$(grep -h kind /var/lib/vr01/run/triton-repo/*/config.pbtxt | sort | uniq -c | tr -s ' ' | tr '\n' ';')"
P=$(probe); step "R7 egress still cut at the end" $([ "$P" = blocked ] && echo PASS || echo FAIL) "probe=$P"
kubectl -n vr01 get pods -o wide > $E/offline-pods-rerun.txt 2>&1
echo "OFFLINE GPU RERUN $(grep -c '^FAIL' $R | grep -q '^0$' && echo PASS || echo FAIL)  $(grep -c '^PASS' $R)/$(grep -c . $R)" | tee -a $R
