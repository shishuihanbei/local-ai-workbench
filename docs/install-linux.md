# Linux 安装与 systemd

适用 Ubuntu / Debian / Fedora / Arch 等主流发行版。

## 1. 依赖

Ubuntu / Debian：

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
```

Fedora：

```bash
sudo dnf install -y python3 python3-virtualenv
```

确认 Python 版本：

```bash
python3 --version   # 需要 3.10 及以上（3.13 可运行，但 OCR 组件只支持 3.10–3.12）
```

## 2. 放置目录

建议放在 `/opt/local-ai-workbench`：

```bash
sudo mkdir -p /opt
sudo chown "$USER":"$USER" /opt
git clone <仓库地址> /opt/local-ai-workbench
cd /opt/local-ai-workbench
```

## 3. 启动

```bash
chmod +x start.sh
./start.sh
```

默认监听 `0.0.0.0:9100`，日志在 `data/logs/`。

```bash
./stop.sh
./restart.sh
PORT=9200 ./start.sh
```

## 4. systemd 常驻

最省事：打开管理控制台 →「部署」页 → 点 **开启开机自启**。以 root 运行时写系统级 unit，普通用户运行时写用户级 unit 并尝试 `enable-linger`；没有 systemd 时自动退回 `crontab @reboot`。

手动方式：仓库带 `deploy/local-ai-workbench.service` 模板和安装脚本。

```bash
sudo bash scripts/install-systemd.sh /opt/local-ai-workbench
```

脚本会创建虚拟环境、安装依赖、写入 `/etc/systemd/system/local-ai-workbench.service` 并启动。

手动方式：

```bash
sudo cp deploy/local-ai-workbench.service /etc/systemd/system/
sudo editor /etc/systemd/system/local-ai-workbench.service
```

把 `User`、`WorkingDirectory`、`ExecStart` 改成实际路径，然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now local-ai-workbench
sudo systemctl status local-ai-workbench
```

查看日志：

```bash
journalctl -u local-ai-workbench -f
```

## 5. Nginx 反向代理（可选）

```nginx
server {
    listen 80;
    server_name ai.example.com;

    client_max_body_size 200m;

    location / {
        proxy_pass http://127.0.0.1:9100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

上公网请加 TLS（Certbot 或云厂商证书），并先阅读 [安全部署](security.md)。

## 6. 防火墙

只给局域网：

```bash
sudo ufw allow from 192.168.1.0/24 to any port 9100
```

公网：

```bash
sudo ufw allow 443/tcp
```

不要直接把 `9100` 暴露到公网。

## 7. 升级

```bash
sudo systemctl stop local-ai-workbench
cp -a data "data-backup-$(date +%Y%m%d)"
git pull
sudo bash scripts/install-systemd.sh /opt/local-ai-workbench
```

数据库迁移在启动时自动执行。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `python3 -m venv` 报 ensurepip | 安装 `python3-venv` |
| 端口占用 | `PORT=9200 ./start.sh` 或改 service 的 `--port` |
| 权限错误 | 整个目录归运行用户，不要用 root 跑前台 |
| 上传大文件 413 | 调大 Nginx `client_max_body_size` |
| 模型在另一台机器 | 填局域网地址，确认对方监听 `0.0.0.0` 且放行端口 |
