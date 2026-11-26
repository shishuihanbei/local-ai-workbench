"""本机部署检测、llama.cpp 安装与 GitHub 多线路回退（Windows / Linux）。"""
from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import platform
import shutil
import time
import zipfile
from pathlib import Path
from typing import Callable

import httpx

from ..config import CREATE_NO_WINDOW, DATA_DIR, IS_WINDOWS, llama_executable, load_config, save_config
from . import hardware, platform_store

GITHUB_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
GITHUB_PROXIES = (
    ("gh-proxy", "https://gh-proxy.com/"),
    ("ghfast", "https://ghfast.top/"),
    ("ghproxy", "https://ghproxy.net/"),
)
BEST_PROXY = ""
STATE: dict = {"running": False, "ok": None, "pct": 0, "step": "", "msg": "尚未安装",
               "error": "", "started_at": 0, "finished_at": 0, "sha256": "", "bytes": 0}
INSTALLER_DIR = DATA_DIR / "installers"


def local_archive() -> Path | None:
    """GitHub 完全打不开时的离线安装包：放进 data/installers 即自动使用。"""
    if not INSTALLER_DIR.exists():
        try:
            INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            return None
    found = [p for p in INSTALLER_DIR.iterdir()
             if p.is_file() and "llama" in p.name.lower() and
             (p.name.lower().endswith(".zip") or p.name.lower().endswith(".tar.gz"))]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None



def _set(**kw):
    STATE.update(kw)


def mirror_prefixes() -> list[str]:
    """`auto` 时按顺序尝试国内常用 GitHub 加速；也可以填自定义前缀。"""
    raw = str(load_config().get("github_proxy") or "auto").strip()
    if raw.lower() in ("off", "direct", "none", "0", "false"):
        return []
    if raw.lower() in ("", "auto"):
        prefixes = [prefix for _, prefix in GITHUB_PROXIES]
        if BEST_PROXY and BEST_PROXY in prefixes:
            prefixes.remove(BEST_PROXY)
            prefixes.insert(0, BEST_PROXY)
        return prefixes
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    if not raw.endswith("/"):
        raw += "/"
    return [raw]


def url_candidates(url: str) -> list[str]:
    """GitHub 链接先直连，再逐个加速；非 GitHub 链接不套代理。"""
    if not url.startswith(("https://github.com/", "https://api.github.com/")):
        return [url]
    prefixes = mirror_prefixes()
    return [url] + [prefix + url for prefix in prefixes]


async def fetch_json(url: str) -> dict | list:
    """GitHub API 取 JSON；直连失败自动换加速，避免部分用户打不开 GitHub。"""
    headers = {"User-Agent": "workbench-installer", "Accept": "application/vnd.github+json"}
    errors: list[str] = []
    timeout = httpx.Timeout(15, connect=8)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        for idx, candidate in enumerate(url_candidates(url)):
            try:
                resp = await c.get(candidate, headers=headers)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                label = "直连" if idx == 0 else "加速"
                detail = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
                errors.append(f"{label}失败：{detail}")
                continue
    raise RuntimeError("GitHub 连接失败（直连和加速都没通）。请点“网络诊断”检查，或在部署页填写可用的加速地址；" +
                       "；".join(errors[-3:]))


def _pick_asset(assets: list[dict], system: str) -> dict | None:
    zips = [a for a in assets if a["name"].endswith((".zip", ".tar.gz"))]
    def rank(a):
        n = a["name"].lower()
        score = 0
        if system == "windows" and "win" in n:
            score += 10
            if "cpu" in n:
                score += 5
            if "x64" in n or "x86_64" in n:
                score += 3
            if "cuda" in n or "cudart" in n or "vulkan" in n or "arm" in n:
                score -= 6
        if system == "linux" and ("ubuntu" in n or "linux" in n):
            score += 10
            if "x64" in n:
                score += 3
            if any(k in n for k in ("vulkan", "cuda", "rocm", "sycl", "openvino", "arm", "s390", "cudart")):
                score -= 8
        return score
    cands = sorted(zips, key=rank, reverse=True)
    return cands[0] if cands and rank(cands[0]) > 0 else None


RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30"


async def _find_release(system: str) -> tuple[dict, dict]:
    """官方 latest 往往只有源码，需要往前翻带预编译包的 release。"""
    rls = await fetch_json(RELEASES_API)
    if not isinstance(rls, list):
        rls = []
    for rel in rls:
        asset = _pick_asset(rel.get("assets", []) or [], system)
        if asset:
            return rel, asset
    r = await fetch_json(GITHUB_API)
    if isinstance(r, dict):
        asset = _pick_asset(r.get("assets", []) or [], system)
        if asset:
            return r, asset
    raise RuntimeError("最近的 release 里没有适合本机的预编译包，请手动安装")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


async def _download(url: str, dest: Path, on_progress: Callable[[int, int, str], None] | None = None) -> str:
    """下载 GitHub 资源；直连失败自动改走加速镜像。"""
    errors: list[str] = []
    candidates = url_candidates(url)
    total = 0
    done = 0
    for idx, candidate in enumerate(candidates):
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(90, connect=8, read=45)) as c:
                async with c.stream("GET", candidate, headers={"User-Agent": "workbench-installer"}) as r:
                    r.raise_for_status()
                    total = int(r.headers.get("content-length") or 0)
                    done = 0
                    with open(dest, "wb") as f:
                        async for chunk in r.aiter_bytes(1024 * 512):
                            f.write(chunk)
                            done += len(chunk)
                            note = "直连" if idx == 0 else "加速镜像"
                            if on_progress:
                                on_progress(done, total, note)
                            elif total:
                                _set(pct=round(min(done / total, 0.99) * 60, 1),
                                     msg=f"{note}下载中 {done/2**20:.0f}/{total/2**20:.0f} MB")
            if total and done != total:
                raise RuntimeError(f"下载不完整：{done}/{total} bytes")
            digest = _sha256(dest)
            _set(sha256=digest, bytes=done)
            return digest
        except Exception as exc:
            errors.append(("直连" if idx == 0 else "加速") + f"失败：{type(exc).__name__}")
            dest.unlink(missing_ok=True)
            continue
    raise RuntimeError("下载失败（直连和加速都没通）。请点“网络诊断”检查网络；" + "；".join(errors[-3:]))


def _check_archive(path: Path) -> None:
    """解压前检查包结构和压缩完整性。"""
    if str(path).endswith(".tar.gz"):
        import tarfile
        with tarfile.open(path) as tf:
            for member in tf.getmembers():
                p = Path(member.name)
                if p.is_absolute() or ".." in p.parts:
                    raise RuntimeError("安装包包含不安全路径")
        return
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"安装包压缩校验失败：{bad}")
        for name in z.namelist():
            p = Path(name)
            if p.is_absolute() or ".." in p.parts:
                raise RuntimeError("安装包包含不安全路径")


def _extract(zip_path: Path, target: Path) -> Path:
    _set(pct=62, step="解压", msg="正在解压安装包")
    _check_archive(zip_path)
    # 解压目录也放在 platforms\.tmp 下，不往系统 %TEMP% 写
    tmp = platform_store.workbench_tmp(load_config(), "llama-extract")
    if str(zip_path).endswith(".tar.gz"):
        import tarfile
        with tarfile.open(zip_path) as tf:
            tf.extractall(tmp, filter="data")
    else:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
    exe_name = "llama-server.exe" if IS_WINDOWS else "llama-server"
    found = list(tmp.rglob(exe_name))
    if not found:
        raise RuntimeError("安装包里没有找到 llama-server")
    src_dir = found[0].parent
    target.mkdir(parents=True, exist_ok=True)
    _set(pct=80, step="安装", msg=f"写入 {target}")
    for item in src_dir.iterdir():
        dst = target / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)
    try:
        if IS_WINDOWS:
            import subprocess
            subprocess.run(["icacls", str(target / exe_name), "/grant", "*S-1-1-0:(RX)"],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            (target / exe_name).chmod(0o755)
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    return target / exe_name


def _install_archive(archive: Path) -> dict:
    cfg = load_config()
    exe = _extract(archive, Path(cfg["llama_dir"]))
    cfg["llama_bin"] = str(exe)
    save_config({**cfg, "llama_bin": str(exe)})
    return {"ok": True, "path": str(exe), "tag": "本地安装包", "sha256": "", "asset": archive.name}


async def install_llama() -> dict:
    if STATE.get("running"):
        return {"ok": False, "msg": "安装已在进行中"}
    system = platform.system().lower()
    if system not in ("windows", "linux"):
        return {"ok": False, "msg": f"当前系统 {system} 暂不支持一键安装，请手动安装 llama.cpp"}
    _set(running=True, ok=None, pct=1, step="检测", msg="获取最新版本信息",
         error="", started_at=time.time(), finished_at=0, sha256="", bytes=0)
    local_error = ""
    archive = local_archive()
    if archive:
        _set(pct=3, step="本地包", msg=f"使用本地安装包 {archive.name}")
        try:
            result = await asyncio.to_thread(_install_archive, archive)
            _set(running=False, ok=True, pct=100, step="完成",
                 msg=f"安装完成：{result['path']}", finished_at=time.time())
            return result
        except Exception as exc:
            local_error = f"本地包安装失败：{exc}"
            _set(step="回退", msg=local_error)
    try:
        rel, asset = await _find_release(system)
        _set(pct=3, step="下载", msg=f"{rel.get('tag_name','')} {asset['name']}")
        cfg = load_config()
        # 安装包统一落在 platforms\.downloads\llama.cpp，下次可直接复用
        archive = platform_store.download_dir(cfg, "llama.cpp") / asset["name"]
        digest = await _download(asset["browser_download_url"], archive)
        exe = _extract(archive, Path(cfg["llama_dir"]))
        cfg["llama_bin"] = str(exe)
        save_config({**cfg, "llama_bin": str(exe)})
        _set(running=False, ok=True, pct=100, step="完成",
             msg=f"安装完成：{exe}", finished_at=time.time())
        return {"ok": True, "path": str(exe), "tag": rel.get("tag_name", ""),
                "sha256": digest, "asset": asset["name"]}
    except Exception as e:
        detail = f"{local_error}；联网安装也失败：{e}" if local_error else str(e)
        _set(running=False, ok=False, step="失败", msg=f"安装失败：{detail}", error=detail,
             finished_at=time.time())
        return {"ok": False, "msg": detail}


def status() -> dict:
    cfg = load_config()
    exe = llama_executable(cfg)
    pkgs = {name: bool(importlib.util.find_spec(name)) for name in ("edge_tts", "mutagen", "httpx")}
    system = platform.system().lower()
    return {
        "platform": system,
        "supported": system in ("windows", "linux"),
        "llama": hardware.llama_info(),
        "models_dir": cfg["models_dir"],
        "models_dir_exists": Path(cfg["models_dir"]).exists(),
        "platforms_dir": cfg.get("platforms_dir", ""),
        "llama_dir": cfg["llama_dir"],
        "python_packages": pkgs,
        "deps_ok": all(pkgs.values()),
        "install": STATE,
        "github_proxy": cfg.get("github_proxy") or "auto",
        "installer_dir": str(INSTALLER_DIR),
        "offline_archive": str(local_archive() or ""),
    }


async def network_check() -> dict:
    """并行检查 GitHub 直连/加速与常用下载站，给一键部署选可用线路。"""
    targets: list[tuple[str, str, str]] = [("GitHub 直连", GITHUB_API, "")]
    prefixes = mirror_prefixes()
    if prefixes:
        for name, prefix in GITHUB_PROXIES:
            if prefix in prefixes:
                targets.append((name + " 加速", prefix + GITHUB_API, prefix))
        for prefix in prefixes:
            if all(prefix != p for _, p in GITHUB_PROXIES):
                targets.append(("自定义加速", prefix + GITHUB_API, prefix))
    else:
        targets.append(("GitHub 加速", "", ""))
    targets += [
        ("PyPI 清华镜像", "https://pypi.tuna.tsinghua.edu.cn/simple/", ""),
        ("Ollama 官网", "https://ollama.com/", ""),
        ("LM Studio 官网", "https://lmstudio.ai/", ""),
    ]

    async def probe(name: str, url: str, prefix: str) -> dict:
        if not url:
            return {"name": name, "ok": False, "ms": None,
                    "detail": "已关闭自动加速，可在输入框填写加速前缀"}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(9, connect=5), follow_redirects=True) as c:
                resp = await c.get(url, headers={"User-Agent": "workbench-installer"})
            ok = 200 <= resp.status_code < 400
            detail = f"HTTP {resp.status_code}"
        except Exception as exc:
            ok = False
            detail = type(exc).__name__
        return {"name": name, "ok": ok, "prefix": prefix,
                "ms": round((time.perf_counter() - started) * 1000), "detail": detail}

    results = await asyncio.gather(*(probe(*t) for t in targets))
    global BEST_PROXY
    usable = [r for r in results if r["ok"] and (r["name"].startswith("GitHub") or r.get("prefix"))]
    pypi = next((r for r in results if r["name"] == "PyPI 清华镜像"), None)
    mirrors = [r for r in usable if r.get("prefix")]
    BEST_PROXY = (min(mirrors, key=lambda r: r["ms"] or 999999).get("prefix") or "") if mirrors else ""
    if usable:
        best = min(usable, key=lambda r: r["ms"] or 999999)
        msg = f"可用线路：{best['name']}（{best['ms']}ms）"
    else:
        msg = "GitHub 直连和加速都不可用，请在部署页填写自己的加速地址，或稍后再试"
    if pypi and not pypi["ok"]:
        msg += "；PyPI 镜像也不可用，vLLM 安装会失败"
    return {"ok": bool(usable), "msg": msg, "results": results,
            "github_proxy": load_config().get("github_proxy") or "auto"}

