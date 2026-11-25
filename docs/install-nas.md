# NAS / Docker 安装

适用群晖 DSM、威联通 QTS、Unraid、TrueNAS SCALE、飞牛 fnOS，以及任何能跑 Docker 的 Linux。

## 1. 架构

镜像支持：

- `linux/amd64`：Intel / AMD NAS、普通 x86 服务器
- `linux/arm64`：树莓派、部分 ARM NAS、Apple Silicon 上的 Docker

模型不打进镜像。把模型目录挂进容器，或在局域网里接 Ollama / LM Studio / vLLM。

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

```bash
git clone <仓库地址> local-ai-workbench
cd local-ai-workbench
```

按实际路径改 `docker-compose.yml` 的 volumes，然后：

```bash
docker compose up -d
docker compose logs -f
```

打开：

```text
http://<NAS 的局域网 IP>:9100/
```

首次进入初始化管理员。

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

```bash
cd local-ai-workbench
docker compose pull
docker compose up -d
```

数据库迁移在容器启动时自动执行。升级前备份 `data/`。

## 10. 常见问题

| 现象 | 处理 |
| --- | --- |
| 容器起来但页面 502 | 看 `docker compose logs`；确认端口和健康检查 |
| `data` 权限错误 | 容器内以 root 运行；把宿主机 `data` 改成可写 |
| ARM NAS 拉不到镜像 | 用 `docker compose build` 在本机构建，或使用多架构镜像 |
| 模型加载失败 | 模型目录映射到 `/models`，控制台里路径填 `/models/xxx.gguf` |
| 上传大文件失败 | 反代调大 `client_max_body_size`，并确认 NAS 空间足够 |
| 重启后数据没了 | 检查 volumes 是否映射到持久目录，而不是容器内 `/data` |
