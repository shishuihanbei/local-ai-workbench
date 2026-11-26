# Windows 安装

适用 Windows 10/11（64 位）。

## 1. 准备 Python

需要 **Python 3.10 及以上**，推荐 3.12（图片 OCR 组件只支持 3.10–3.12）。

- 从 [python.org](https://www.python.org/downloads/windows/) 下载 3.12 安装包。
- 安装时勾选 **Add python.exe to PATH**。
- 验证：

```powershell
python --version
```

如果系统里有多个 Python，启动脚本会优先找 3.12、3.11、3.10；只剩 3.13 也能启动，但 OCR 组件不可用。

## 2. 解压

把仓库下载或 `git clone` 到普通目录，例如：

```text
D:\LocalAI\workbench
```

不要放 `C:\Program Files`、OneDrive 同步目录或含中文空格的深层路径，避免权限和编码问题。

## 3. 一键启动

双击 `start.bat`。

首次启动会自动：

1. 创建 `data/`、日志和上传目录。
2. 创建 `.venv`。
3. 安装 `requirements.txt`。
4. 后台启动服务。
5. 打开 `http://127.0.0.1:9100/`。

命令行也可以：

```powershell
.\start.ps1
```

换端口：

```powershell
.\start.ps1 -Port 9200
```

不自动开浏览器：

```powershell
.\start.ps1 -NoBrowser
```

## 4. 首次配置

1. 打开 `http://127.0.0.1:9100/`。
2. 数据库为空时，页面提示初始化管理员，设置账号和强密码。
3. 登录后进入 `http://127.0.0.1:9100/console/`。
4. 在「部署」或「供应商」页接入模型。

## 5. 局域网访问

启动脚本默认监听 `0.0.0.0:9100`，同一局域网的设备可以访问：

```text
http://<这台电脑的局域网 IP>:9100/
```

Windows 防火墙首次会弹提示，选择 **专用网络** 允许。只在自己信任的网络里开放；公网访问前先看 [安全部署](security.md)。

## 6. 开机自启（可选）

方法一：任务计划程序

- 触发器：登录时
- 操作：启动程序 `powershell.exe`
- 参数：`-NoProfile -ExecutionPolicy Bypass -File "D:\LocalAI\workbench\start.ps1" -NoBrowser`
- 起始于：`D:\LocalAI\workbench`

方法二：把 `start.bat` 的快捷方式放进：

```text
shell:startup
```

## 7. 停止与升级

```powershell
.\stop.bat
.\restart.bat
```

升级：

1. 先 `.\stop.bat`。
2. 备份整个 `data/`。
3. 用新版覆盖代码目录，保留 `data/`、`models/`、`.venv`。
4. 再 `.\start.bat`，数据库会自动迁移。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 提示找不到 Python | 安装 3.12 并勾选 PATH，或 `.\start.ps1 -PythonExe "C:\Python312\python.exe"` |
| 端口被占用 | `.\start.ps1 -Port 9200` |
| 页面打不开 | 看 `data\logs\start-9100.err`，再 `.\stop.bat` 后重启 |
| 依赖安装很慢 | 设置 `PIP_INDEX_URL` 为国内镜像 |
| 杀毒软件拦截 | 将项目目录加入信任；脚本只在本机建 venv 和启动 Python |
| 想恢复旧数据 | 停服务，覆盖 `data/`，再启动 |
