#!/bin/bash
# Bai kiem goi offline tren node kubeadm lab: tao goi -> CAT Internet -> xoa image + namespace -> cai tu goi -> smoke.
# Chay trong mvp/ (root). SSH dang mo van giu. CHUA CHAY THU.
set -uo pipefail
OUT="${OUT:-/root/k8s-evidence}"; mkdir -p "$OUT"; R="$OUT/offline-report.txt"; : > "$R"; FAIL=0; B=/root/vr01-app-bundle
step(){ if [ "$2" = ok ]; then echo "PASS  $1  $3" | tee -a "$R"; else echo "FAIL  $1  $3" | tee -a "$R"; FAIL=1; fi; }
probe(){ for u in https://nvcr.io https://registry-1.docker.io https://github.com http://1.1.1.1; do curl -s -m 4 -o /dev/null "$u" && { echo open; return; }; done; echo blocked; }
deploy/k8s/make_offline_bundle.sh "$B" > "$OUT/bundle-make.log" 2>&1; rc=$?
step "O1 build offline app bundle" $([ $rc = 0 ] && echo ok || echo no) "size $(du -sh $B 2>/dev/null | cut -f1), files $(wc -l < $B/SHA256SUMS 2>/dev/null)"
cp "$B/SHA256SUMS" "$B/BUNDLE-INFO.txt" "$OUT/" 2>/dev/null
# Cat ket noi MOI ra Internet (giu loopback, mang pod/service, ket noi da thiet lap nhu SSH dang mo).
iptables -I OUTPUT 1 -o lo -j ACCEPT; iptables -I OUTPUT 2 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -I OUTPUT 3 -d 10.0.0.0/8 -j ACCEPT; iptables -I OUTPUT 4 -d 172.16.0.0/12 -j ACCEPT; iptables -I OUTPUT 5 -d 192.168.0.0/16 -j ACCEPT
iptables -I OUTPUT 6 -d "$(hostname -I | awk '{print $1}')" -j ACCEPT; iptables -I OUTPUT 7 -j REJECT
iptables -I FORWARD 1 -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT; iptables -I FORWARD 2 ! -d 10.0.0.0/8 -o "$(ip route show default | awk '{print $5; exit}')" -j REJECT
P=$(probe); step "O2 Internet egress cut on the node" $([ "$P" = blocked ] && echo ok || echo no) "probe=$P"
kubectl delete namespace vr01 --ignore-not-found --wait=true >/dev/null 2>&1; kubectl delete pv vr01-run --ignore-not-found >/dev/null 2>&1
for ref in $(ctr -n k8s.io images ls -q | grep -E "tritonserver|vr01-mvp-api"); do ctr -n k8s.io images rm "$ref" >/dev/null 2>&1; done
LEFT=$(ctr -n k8s.io images ls -q | grep -c -E "tritonserver|vr01-mvp-api")
step "O3 app images removed from the node before offline install" $([ "$LEFT" = 0 ] && echo ok || echo no) "left=$LEFT"
T0=$(date +%s); bash "$B/mvp/deploy/k8s/install_offline.sh" "$B" > "$OUT/offline-install.log" 2>&1; rc=$?
step "O4 install from the bundle with egress cut" $([ $rc = 0 ] && echo ok || echo no) "$(( $(date +%s)-T0 ))s; $(tail -1 "$OUT/offline-install.log" | cut -c1-60)"
for _ in $(seq 1 60); do [ "$(curl -sk -m 3 -o /dev/null -w '%{http_code}' https://127.0.0.1:30943/readyz)" = 200 ] && break; sleep 1; done
(cd "$B/mvp" && python3 tests/smoke.py --run-dir /var/lib/vr01/run --inference-port 30443 --management-port 30943 --output "$OUT/offline-smoke.json") > "$OUT/offline-smoke.log" 2>&1
step "O5 smoke flow on the offline-installed stack (tools from the bundle)" $([ $? = 0 ] && echo ok || echo no) "$(tail -1 "$OUT/offline-smoke.log" | cut -c1-40)"
PULLS=$(kubectl -n vr01 get events 2>/dev/null | grep -c -E "Pulling image|ErrImagePull|ImagePullBackOff")
step "O6 no image pull was attempted" $([ "$PULLS" = 0 ] && echo ok || echo no) "pull events=$PULLS"
P=$(probe); step "O7 egress still cut at the end" $([ "$P" = blocked ] && echo ok || echo no) "probe=$P"
kubectl -n vr01 get pods -o wide > "$OUT/offline-pods.txt" 2>&1; iptables -S OUTPUT > "$OUT/offline-iptables.txt" 2>&1
echo "OFFLINE CHECK $([ $FAIL = 0 ] && echo PASS || echo FAIL)  $(grep -c '^PASS' "$R")/$(grep -c . "$R")  (egress stays cut; reboot or flush iptables to restore)" | tee -a "$R"; exit $FAIL
