#!/bin/bash
# Dung kubeadm single-node CHO LAB tren may GPU cua provider (da co driver NVIDIA + Docker + NVIDIA Container Toolkit),
# co Internet. Them NVIDIA device plugin de pod xin duoc nvidia.com/gpu. CHUA CHAY THU (viet 11/10/2026).
# KHONG phai bo cai air gap (bo offline da kiem cua du an la r4.x).
set -euo pipefail
K8S_MINOR="${K8S_MINOR:-v1.34}"; POD_CIDR="${POD_CIDR:-10.244.0.0/16}"
export DEBIAN_FRONTEND=noninteractive
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
command -v nvidia-ctk >/dev/null || { echo "thieu NVIDIA Container Toolkit (nvidia-ctk)"; exit 1; }
swapoff -a; sed -i -E '/[[:space:]]swap[[:space:]]/ s/^/#/' /etc/fstab || true
modprobe overlay; modprobe br_netfilter
printf 'overlay\nbr_netfilter\n' > /etc/modules-load.d/k8s.conf
printf 'net.bridge.bridge-nf-call-iptables=1\nnet.bridge.bridge-nf-call-ip6tables=1\nnet.ipv4.ip_forward=1\n' > /etc/sysctl.d/k8s.conf
sysctl --system >/dev/null
apt-get update -qq && apt-get install -y -qq make git curl gpg apt-transport-https ca-certificates >/dev/null
command -v containerd >/dev/null || apt-get install -y -qq containerd >/dev/null
mkdir -p /etc/containerd && containerd config default | sed 's/SystemdCgroup = false/SystemdCgroup = true/' > /etc/containerd/config.toml
# runtime nvidia lam mac dinh cho containerd (CRI) de device plugin va pod GPU chay duoc
nvidia-ctk runtime configure --runtime=containerd --set-as-default >/dev/null
systemctl restart containerd
mkdir -p /etc/apt/keyrings
curl -fsSL "https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/Release.key" | gpg --dearmor --yes -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/${K8S_MINOR}/deb/ /" > /etc/apt/sources.list.d/kubernetes.list
apt-get update -qq && apt-get install -y -qq kubelet kubeadm kubectl >/dev/null && apt-mark hold kubelet kubeadm kubectl >/dev/null
kubeadm init --pod-network-cidr="$POD_CIDR" --cri-socket unix:///run/containerd/containerd.sock | tail -5
mkdir -p /root/.kube && cp -f /etc/kubernetes/admin.conf /root/.kube/config
kubectl taint nodes --all node-role.kubernetes.io/control-plane- || true
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.30.2/manifests/calico.yaml >/dev/null
kubectl wait --for=condition=Ready node --all --timeout=300s
kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/v0.17.1/deployments/static/nvidia-device-plugin.yml >/dev/null
echo "waiting for nvidia.com/gpu to be allocatable..."
for _ in $(seq 1 60); do G=$(kubectl get nodes -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'); [ -n "$G" ] && [ "$G" != 0 ] && break; sleep 5; done
echo "ALLOCATABLE_GPU=${G:-0}"; [ "${G:-0}" != 0 ]
kubectl get nodes -o wide; kubeadm version -o short; containerd --version
