# macOS 安装

适用 macOS 12 及以上，Intel 与 Apple Silicon 均可。

## 1. 安装 Python

推荐 Homebrew：

```bash
brew install python@3.12
python3.12 --version
```

也可以从 [python.org](https://www.python.org/downloads/macos/) 安装 3.12。

工作台本身不需要 Xcode；如果编译 OCR 可选组件，才需要命令行工具。

## 2. 下载并启动

```bash
git clone <仓库地址> local-ai-workbench
cd local-ai-workbench
chmod +x start.sh start-macos.command
./start.sh
```

或者直接在 Finder 里双击 `start-macos.command`。首次运行若被 Gatekeeper 拦住：

- 右键 → **打开** → 再确认一次。
- 或在“系统设置 → 隐私与安全性”里允许。

启动成功后打开：

```text
http://127.0.0.1:9100/
```

管理控制台：

```text
http://127.0.0.1:9100/console/
```

## 3. 首次配置

1. 初始化管理员账号。
2. 控制台「供应商」或「部署」页接入模型。
3. 如果模型跑在另一台机器上，填它的局域网地址，例如 `http://192.168.1.20:11434/v1`。

## 4. 后台运行与停止

```bash
./start.sh        # 后台启动
./stop.sh         # 停止
./restart.sh      # 重启
tail -f data/logs/app.log
```

端口：

```bash
PORT=9200 ./start.sh
```

## 5. 开机自启（launchd）

最简单：打开管理控制台 →「部署」页 → 点 **开启开机自启**，会自动写好并加载 ~/Library/LaunchAgents/com.local-ai-workbench.plist；再点一次即可卸载删除。

也可以手动安装。仓库自带模板 `deploy/com.local-ai-workbench.plist`。先生成并安装：

```bash
bash scripts/install-launchd.sh
```

脚本会：

- 读取当前项目绝对路径；
- 生成 `~/Library/LaunchAgents/com.local-ai-workbench.plist`；
- 加载服务。

管理：

```bash
launchctl list | grep local-ai-workbench
launchctl unload ~/Library/LaunchAgents/com.local-ai-workbench.plist
launchctl load ~/Library/LaunchAgents/com.local-ai-workbench.plist
```

日志在 `data/logs/launchd.out` 和 `data/logs/launchd.err`。

## 6. 升级

```bash
./stop.sh
cp -R data data-backup-$(date +%Y%m%d)
git pull
./start.sh
```

数据库会自动迁移。`data/secret.key` 必须保留，否则供应商 Key 无法解密。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `command not found: python3` | 安装 Homebrew Python，或 `brew link python@3.12` |
| `.command` 双击没反应 | `chmod +x start-macos.command`；右键打开 |
| 端口被占用 | `PORT=9200 ./start.sh` |
| Apple Silicon 上依赖编译失败 | 用 Python 3.12 官方安装包；不要混用 Rosetta 与 arm64 的 Python |
| 局域网访问不了 | 系统设置 → 防火墙 → 允许 Python 入站 |
