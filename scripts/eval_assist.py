"""混合架构评测：同一批用例跑本地为主链路，记录补强命中、耗时与质量。

用法：
  python scripts/eval_assist.py --base http://127.0.0.1:9100 --user admin --password 你的密码
  python scripts/eval_assist.py --cases scripts/eval_cases.jsonl --out data/eval-assist.json

用例 JSONL 每行：
  {"id":"weekly","message":"...","expect_any":["周","进度"],"forbid_any":["抱歉"]}
  {"id":"secret","message":"身份证 110101...","sensitive":true}
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT / "scripts" / "eval_cases.jsonl"


def login(base: str, user: str, password: str) -> str:
    r = httpx.post(f"{base}/api/auth/login", json={"username": user, "password": password}, timeout=20)
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token") or data.get("token")
    if not token:
        raise SystemExit("登录成功但没有拿到 access_token")
    return token


def run_case(base: str, token: str, case: dict, timeout: float) -> dict:
    body = {"message": case["message"], "agent_mode": bool(case.get("agent_mode", False))}
    if case.get("assist_reason"):
        body["assist_reason"] = str(case["assist_reason"])[:80]
    elif case.get("sensitive"):
        body["assist_reason"] = "敏感用例"
    started = time.monotonic()
    meta: dict = {}
    text_parts: list[str] = []
    error = ""
    status = 0
    try:
        with httpx.stream("POST", f"{base}/api/chat/stream",
                          headers={"Authorization": "Bearer " + token},
                          json=body, timeout=timeout) as r:
            status = r.status_code
            if r.status_code == 403 and case.get("sensitive"):
                return {"id": case["id"], "ok": True, "status": 403,
                        "gate": "sensitive_blocked", "ms": 0, "chars": 0}
            if r.status_code != 200:
                error = f"HTTP {r.status_code}"
            else:
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if not payload:
                        continue
                    try:
                        evt = json.loads(payload)
                    except Exception:
                        continue
                    if evt.get("type") == "meta":
                        meta = evt
                    elif evt.get("type") == "delta":
                        text_parts.append(str(evt.get("text") or ""))
                    elif evt.get("type") == "assist":
                        meta["assist_event"] = evt
                    elif evt.get("type") == "error":
                        error = str(evt.get("message") or "error")
    except Exception as exc:
        error = str(exc)[:300]
    text = "".join(text_parts)
    elapsed = int((time.monotonic() - started) * 1000)
    expect = [w for w in case.get("expect_any") or [] if w]
    forbid = [w for w in case.get("forbid_any") or [] if w]
    hit = all(w in text for w in expect) if expect else bool(text.strip())
    clean = not any(w in text for w in forbid)
    ok = (not error) and hit and clean and bool(text.strip())
    return {
        "id": case["id"], "ok": ok, "status": status, "error": error,
        "route": meta.get("route") or "", "assist": meta.get("assist") or None,
        "assist_event": meta.get("assist_event") or None,
        "provider": meta.get("provider") or "", "model": meta.get("model") or "",
        "ms": elapsed, "chars": len(text),
        "missing": [w for w in expect if w not in text],
        "forbidden_hit": [w for w in forbid if w in text],
        "text": text[:600],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:9100")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="")
    ap.add_argument("--token", default="")
    ap.add_argument("--cases", default=str(DEFAULT_CASES))
    ap.add_argument("--out", default=str(ROOT / "data" / "eval-assist.json"))
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args()
    if not args.token and not args.password:
        raise SystemExit("请传 --password 或 --token")

    token = args.token or login(args.base, args.user, args.password)
    cases = [json.loads(line) for line in Path(args.cases).read_text("utf-8").splitlines() if line.strip()]
    results = [run_case(args.base, token, c, args.timeout) for c in cases]
    total = len(results)
    passed = sum(1 for r in results if r["ok"])
    assisted = sum(1 for r in results if r.get("route") == "assist" or r.get("assist_event"))
    avg_ms = int(sum(r["ms"] for r in results) / total) if total else 0
    summary = {
        "total": total, "passed": passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0.0,
        "assist_used": assisted, "avg_ms": avg_ms,
        "failed_ids": [r["id"] for r in results if not r["ok"]],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "results": results},
                              ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n明细已写入 {out}")
    for r in results:
        if not r["ok"]:
            print(f"- {r['id']}: error={r['error']} missing={r['missing']} forbidden={r['forbidden_hit']}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
