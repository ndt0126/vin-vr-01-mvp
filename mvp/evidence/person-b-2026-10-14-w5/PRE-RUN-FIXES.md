# Sửa README trước lượt người B (14/10/2026), do tác giả phát hiện khi chuẩn bị lượt

Máy: DeployGPU `d7741cfd…` (RTX A6000, Ubuntu 24.04.4, driver 580.126.16, Docker CE 29.2.1 + Compose 5.0.2 + NVIDIA Container Toolkit 1.18.2 có sẵn trong image nhà cung cấp).

1. **Quick start ra lệnh `apt-get install docker.io docker-compose-v2 …`**: trên máy đã có Docker CE, `apt-get install -s` báo `containerd.io : Conflicts: containerd` và `pkgProblemResolver::Resolve generated breaks` → người B sẽ bị chặn ngay bước đầu. Sửa ở commit `905dc2b`: nếu máy đã có Docker thì chỉ cài `make git python3`.
2. **Mục "Giao diện trạm" ghi "Node.js ≥ 20" mà không nói cách cài**; Ubuntu 24.04 chỉ có Node 18 qua apt (Playwright 1.55 chạy được với Node 18). Sửa ở commit `df28aab`: "Node.js ≥ 18, npm … `apt-get install -y nodejs npm`".

Lượt người B chạy trên commit `df28aab` (đã gồm hai sửa trên).
