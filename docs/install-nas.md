# NAS / Docker 安装

适用群晖 DSM、威联通 QTS、Unraid、TrueNAS SCALE、飞牛 fnOS，以及任何能跑 Docker 的 Linux。

## 1. 架构

镜像支持：

- `linux/amd64`：Intel / AMD NAS、普通 x86 服务器
- `linux/arm64`：树莓派、部分 ARM NAS、Apple Silicon 上的 Docker

模型不打进镜像。把模型目录挂进容器，或在局域网里接 Ollama / LM Studio / vLLM。

容器里只跑 Web 服务和数据库。想在本机推理，模型服务（Ollama 等）放在宿主机或另一台机器，容器里用 `http://host.docker.internal:11434` 访问；容器内没有 GPU 直通，不要把 llama.cpp 二进制塞进容器里跑。

## 2. 目录规划

建议在 NAS 上建：

```text
/volume1/docker/local-ai-workbench/
├── data/          # 数据库、配置、上传、日志
├── models/        # GGUF 模型（可选）
└── llama/         # llama.cpp 可执行文件（可选）
```

`data/` 必须可写，且要纳入备份。`models/` 可以很大，不必备份。

## 3. Docker Compose

两种方式，任选一种：

**A. 用源码本地构建**（不需要拉镜像，第一次要装依赖，几分钟）

```bash
git clone <仓库地址> local-ai-workbench
cd local-ai-workbench
docker compose up -d --build
docker compose logs -f
```

国内网络 pip 慢的话，改用：

```bash
docker compose build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
docker compose up -d
```

要让图片和扫描件也能识别文字（OCR），构建时加上：

```bash
docker compose build --build-arg INSTALL_OCR=1
docker compose up -d
```

**B. 直接用镜像**（不构建，速度最快）

```bash
# 私有仓库里的镜像需要先登录；仓库转公开后可去掉登录
echo <你的 GitHub Token> | docker login ghcr.io -u <你的 GitHub 用户名> --password-stdin
docker pull ghcr.io/shishuihanbei/local-ai-workbench:latest
docker run -d --name local-ai-workbench --restart unless-stopped \
  -p 9100:9100 \
  -v /volume1/docker/local-ai-workbench/data:/data \
  -e WORKBENCH_DATA=/data -e WORKBENCH_SERVE_FRONTEND=1 \
  --add-host host.docker.internal:host-gateway \
  ghcr.io/shishuihanbei/local-ai-workbench:latest
```

打开：

```text
http://<NAS 的局域网 IP>:9100/
```

首次进入初始化管理员。

`data/` 目录首次启动会生成 `workbench.db` 和 `secret.key`，两个文件必须一起备份；丢 `secret.key` 后已保存的供应商 API Key 解不开。

## 4. 群晖 DSM

1. **套件中心**安装 Container Manager。
2. **File Station** 在 `docker/local-ai-workbench` 下建 `data`、`models`。
3. 把仓库里的 `docker-compose.yml` 上传到该目录。
4. Container Manager → **项目** → 新增 → 选择该目录的 compose 文件。
5. 端口映射 `9100:9100`，数据目录映射 `/volume1/docker/local-ai-workbench/data:/data`。
6. 启动后访问 `http://群晖IP:9100/`。

如果 DSM 防火墙开启，在“控制面板 → 安全性 → 防火墙”放行 9100，仅限内网。

## 5. 威联通 QTS

1. App Center 安装 Container Station。
2. 创建共享文件夹 `docker/local-ai-workbench`。
3. Container Station → **应用程序** → 创建 → 粘贴 compose 内容。
4. 确认 `data` 卷映射和 9100 端口。
5. 启动并访问 `http://NAS_IP:9100/`。

## 6. Unraid

1. 安装 **Docker Compose Manager** 插件（或直接用终端）。
2. 在 `/mnt/user/appdata/local-ai-workbench` 放 compose 文件。
3. 改 volumes 为：

```yaml
volumes:
  - /mnt/user/appdata/local-ai-workbench/data:/data
  - /mnt/user/models:/models
```

4. `docker compose up -d`。

## 7. TrueNAS SCALE

1. 创建 dataset：`apps/local-ai-workbench/data`。
2. Apps → **Custom App**，或用 Shell 运行 compose。
3. 挂载 `data` dataset 到 `/data`。
4. 端口 9100，重启策略 `unless-stopped`。

## 8. 反向代理与 HTTPS

NAS 自带的反向代理（群晖 Application Portal、威联通 Reverse Proxy、Unraid Nginx Proxy Manager）都可以：

- 前端地址：`http://127.0.0.1:9100`
- 开启 WebSocket / 长连接
- 上传大小调到 200MB 以上
- 只对自己的域名开放，不要让 9100 直接暴露公网

## 9. 升级

源码构建方式：

```bash
cd local-ai-workbench
git pull
docker compose up -d --build
```

镜像方式：

```bash
docker compose pull
docker compose up -d
```

数据库迁移在容器启动时自动执行。升级前备份 `data/`（含 `secret.key`）。

## 10. 常见问题

| 现象 | 处理 |
| --- | --- |
| 容器起来但页面 502 | 看 `docker compose logs`；确认端口和健康检查 |
| `docker compose pull` 拉不到镜像 | 私有镜像要先 `docker login ghcr.io`；或者直接 `docker compose up -d --build` 本地构建 |
| `data` 权限错误 | 容器内以 root 运行，文件属主是 root；需要 DSM 里读写就 `sudo chown -R 你的用户 data` |
| ARM NAS 拉不到镜像 | 用 `docker compose up -d --build` 在本机构建，CI 已提供 `linux/arm64` 多架构镜像 |
| 模型加载失败 | 模型目录映射到 `/models`，控制台里路径填 `/models/xxx.gguf` |
| 容器内看不到宿主机模型服务 | 用 `http://host.docker.internal:11434`（compose 已加 `extra_hosts`），别填 `127.0.0.1` |
| 上传大文件失败 | 反代调大 `client_max_body_size`，并确认 NAS 空间足够 |
| 重启后数据没了 | 检查 volumes 是否映射到持久目录，而不是容器内 `/data` |
