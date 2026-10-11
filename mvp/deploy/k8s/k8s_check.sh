#!/bin/bash
# Bai kiem W4-03 tren cluster that. Chay trong thu muc mvp/ tren node (root, co kubectl). CHUA CHAY THU.
# Deploy tu namespace sach -> pod Ready dung dieu kien -> smoke qua NodePort -> xoa pod (tu phuc hoi)
# -> rollout ban moi -> rollout undo -> rollback model. Ghi ket qua vao $OUT/k8s-report.txt.
set -uo pipefail
OVERLAY="${OVERLAY:-deploy/k8s/overlays/lab-cpu}"; RUN=/var/lib/vr01/run; OUT="${OUT:-/root/k8s-evidence}"; mkdir -p "$OUT"
R="$OUT/k8s-report.txt"; : > "$R"; FAIL=0
step(){ if [ "$2" = ok ]; then echo "PASS  $1  $3" | tee -a "$R"; else echo "FAIL  $1  $3" | tee -a "$R"; FAIL=1; fi; }
ctl(){ python3 tools/vr01ctl.py --run-dir "$RUN" --inference-port 30443 --management-port 30943 "$@"; }
ready(){ kubectl -n vr01 rollout status deploy/vr01-inspection --timeout=300s >/dev/null 2>&1; }
T0=$(date +%s)
kubectl delete namespace vr01 --ignore-not-found --wait=true >/dev/null 2>&1
kubectl apply -k "$OVERLAY" > "$OUT/apply.log" 2>&1 && ready; rc=$?
step "K1 deploy from a clean namespace, rollout complete" $([ $rc = 0 ] && echo ok || echo no) "$(( $(date +%s)-T0 ))s"
kubectl -n vr01 get pods -o wide > "$OUT/pods.txt" 2>&1; kubectl -n vr01 describe deploy/vr01-inspection > "$OUT/describe-deploy.txt" 2>&1
RD=$(kubectl -n vr01 get pod -l app.kubernetes.io/name=vr01-inspection -o jsonpath='{.items[0].status.containerStatuses[*].ready}')
step "K2 both containers Ready (api readiness = active recipe verified + model loaded)" $([ "$RD" = "true true" ] && echo ok || echo no) "ready=[$RD]"
ctl status > "$OUT/status-1.txt" 2>&1; step "K3 vr01ctl status through NodePort" $([ $? = 0 ] && echo ok || echo no) "$(head -2 "$OUT/status-1.txt" | tr '\n' ' ')"
python3 tests/smoke.py --run-dir "$RUN" --inference-port 30443 --management-port 30943 --output "$OUT/smoke-1.json" > "$OUT/smoke-1.log" 2>&1
step "K4 smoke flow through NodePort" $([ $? = 0 ] && echo ok || echo no) "$(tail -1 "$OUT/smoke-1.log" | cut -c1-40)"
POD_IP=$(kubectl -n vr01 get pod -l app.kubernetes.io/name=vr01-inspection -o jsonpath='{.items[0].status.podIP}')
C=$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://$POD_IP:8000/v2/health/ready" || true)
step "K5 Triton port 8000 is not reachable on the pod IP" $([ "$C" = 000 ] && echo ok || echo no) "http=$C"
BEFORE=$(ctl status | sed -n 2p); T1=$(date +%s)
kubectl -n vr01 delete pod -l app.kubernetes.io/name=vr01-inspection --wait=true >/dev/null 2>&1; ready; rc=$?
AFTER=$(ctl status | sed -n 2p)
step "K6 pod deleted -> recreated, same active recipe" $([ $rc = 0 ] && [ "$BEFORE" = "$AFTER" ] && echo ok || echo no) "$(( $(date +%s)-T1 ))s; $AFTER"
REV1=$(kubectl -n vr01 get deploy vr01-inspection -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}'); T2=$(date +%s)
kubectl -n vr01 patch deploy vr01-inspection --type merge -p '{"spec":{"template":{"metadata":{"annotations":{"vr01.io/release":"0.1.1-test"}}}}}' >/dev/null && ready; rc=$?
REV2=$(kubectl -n vr01 get deploy vr01-inspection -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}')
step "K7 update to a new release revision" $([ $rc = 0 ] && [ "$REV2" != "$REV1" ] && echo ok || echo no) "rev $REV1 -> $REV2, $(( $(date +%s)-T2 ))s"
T3=$(date +%s); kubectl -n vr01 rollout undo deploy/vr01-inspection >/dev/null && ready; rc=$?
REL=$(kubectl -n vr01 get deploy vr01-inspection -o jsonpath='{.spec.template.metadata.annotations.vr01\.io/release}')
step "K8 rollback to the previous release (rollout undo)" $([ $rc = 0 ] && [ "$REL" = "0.1.0" ] && echo ok || echo no) "release=$REL, $(( $(date +%s)-T3 ))s"
ctl activate recipe-a --reason "k8s check" >/dev/null 2>&1; ctl activate recipe-b --reason "k8s check" > "$OUT/activate.txt" 2>&1; a=$?
ctl rollback --reason "k8s check rollback" > "$OUT/rollback.txt" 2>&1; b=$?
step "K9 model switch and model rollback" $([ $a = 0 ] && [ $b = 0 ] && grep -q "recipe-b@0.1.0 -> recipe-a@0.1.0" "$OUT/rollback.txt" && echo ok || echo no) "$(head -1 "$OUT/rollback.txt")"
python3 tests/smoke.py --run-dir "$RUN" --inference-port 30443 --management-port 30943 --output "$OUT/smoke-2.json" > "$OUT/smoke-2.log" 2>&1
step "K10 smoke flow after update/rollback" $([ $? = 0 ] && echo ok || echo no) "$(tail -1 "$OUT/smoke-2.log" | cut -c1-40)"
kubectl -n vr01 get all,networkpolicy -o wide > "$OUT/get-all.txt" 2>&1; kubectl -n vr01 rollout history deploy/vr01-inspection > "$OUT/rollout-history.txt" 2>&1
kubectl -n vr01 logs deploy/vr01-inspection -c api --tail=200 > "$OUT/api.log" 2>&1; kubectl -n vr01 logs deploy/vr01-inspection -c triton --tail=200 > "$OUT/triton.log" 2>&1
(kubectl version; kubeadm version -o short; containerd --version; kubectl get nodes -o wide) > "$OUT/versions.txt" 2>&1
echo "K8S CHECK $([ $FAIL = 0 ] && echo PASS || echo FAIL)  $(grep -c '^PASS' "$R")/$(grep -c . "$R")" | tee -a "$R"; exit $FAIL
