#!/bin/bash
# Dung mot cluster kubeadm single-node CHO LAB tren VPS Ubuntu (CPU, CO Internet). CHUA CHAY THU.
# KHONG phai bo cai air gap: bo cai offline da kiem cua du an la r4.x (docs/Tuan_1c). Script nay chi de co
# mot cluster kubeadm that de thu manifests cua MVP.
set -euo pipefail
K8S_MINOR="${K8S_MINOR:-v1.34}"; POD_CIDR="${POD_CIDR:-10.244.0.0/16}"
export DEBIAN_FRONTEND=noninteractive
swapoff -a; sed -i -E '/[[:space:]]swap[[:space:]]/ s/^/#/' /etc/fstab || true
modprobe overlay; modprobe br_netfilter
printf 'overlay\nbr_netfilter\n' > /etc/modules-load.d/k8s.conf
printf 'net.bridge.bridge-nf-call-iptables=1\nnet.bridge.bridge-nf-call-ip6tables=1\nnet.ipv4.ip_forward=1\n' > /etc/sysctl.d/k8s.conf
sysctl --system >/dev/null
apt-get update -qq && apt-get install -y -qq containerd docker.io docker-compose-v2 make git curl gpg apt-transport-https ca-certificates >/dev/null
mkdir -p /etc/containerd && containerd config default | sed 's/SystemdCgroup = false/SystemdCgroup = true/' > /etc/containerd/config.toml
systemctl restart containerd
mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/Release.key" | gpg --dearmor --yes -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/ /" > /etc/apt/sources.list.d/kubernetes.list
apt-get update -qq && apt-get install -y -qq kubelet kubeadm kubectl >/dev/null && apt-mark hold kubelet kubeadm kubectl >/dev/null
kubeadm init --pod-network-cidr="$POD_CIDR" --cri-socket unix:///run/containerd/containerd.sock | tail -5
mkdir -p /root/.kube && cp -f /etc/kubernetes/admin.conf /root/.kube/config
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
# Calico (ho tro NetworkPolicy), pin phien ban
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.30.2/manifests/calico.yaml >/dev/null
echo "waiting for node Ready..."; kubectl wait --for=condition=Ready node --all --timeout=300s
kubectl get nodes -o wide; kubeadm version -o short; containerd --version
