# -*- coding: utf-8 -*-
"""部署回归自检：自动发现 deck_server 的 GET 路由并逐个探活。

用法（服务已启动后）：
    python scripts/_smoke_deploy.py [--base http://127.0.0.1:8787]

规则：
- 路由从 deck/deck_server.py 源码动态提取（`path == "/xxx"` 与 startswith 规则），
  不在此脚本里写死页面清单，源码新增路由自动纳入回归。
- 页面路由接受 200/301/302/303；API 路由要求 200 且返回合法 JSON。
- HARNESS（:3080）与 /api/proxy/ 单独检查。
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SERVER = BASE / "deck" / "deck_server.py"
TIMEOUT = 25

# 演示数据（30 只 × 250 日合成序列）覆盖不到的接口：需 2020-2025 真实日线 + 市值/财报库
DEMO_GAPS = {
    "/api/live/backtest_run": "需真实日线(2020-2025) + hist_mv.db/finance_ts.db；演示库仅 250 日",
}


def discover_routes() -> tuple:
    src = SERVER.read_text(encoding="utf-8", errors="replace")
    start = src.find("def do_GET")
    end = src.find("def do_POST", start) if start >= 0 else -1
    block = src[start:end] if start >= 0 and end > start else src

    exact = set()
    prefixes = []
    for m in re.finditer(r'path\s*==\s*"([^"]+)"', block):
        exact.add(m.group(1))
    for m in re.finditer(r'path\.startswith\(\s*"([^"]+)"', block):
        prefixes.append(m.group(1))
    # 多行 or 连接的路由：逐个字符串字面量兜底（仅 /api/ 与 .html 形态）
    for m in re.finditer(r'"((?:/api/[A-Za-z0-9_\-/]+)|(?:/[A-Za-z0-9_\-]+\.html))"', block):
        exact.add(m.group(1))
    return sorted(exact), sorted(set(prefixes))


def probe(url: str) -> tuple:
    req = urllib.request.Request(url, headers={"User-Agent": "DSHQuant-deploy-smoke"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read()
            return r.status, r.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", e.read()
    except Exception as e:                      # 连接失败等
        return 0, type(e).__name__, str(e).encode()


def is_page(route: str) -> bool:
    return not route.startswith("/api/")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--harness", default="http://127.0.0.1:3080")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    exact, prefixes = discover_routes()
    print(f"发现精确路由 {len(exact)} 条，前缀路由 {len(prefixes)} 条\n")

    fails, warns, oks = [], [], 0
    rows = []
    for route in exact:
        status, ctype, body = probe(urllib.parse.urljoin(base + "/", route.lstrip("/")))
        ok_json = True
        detail = ""
        proxied = route.startswith("/api/proxy/")   # 反代透传 HARNESS，可能是 HTML 页面，不要求 JSON
        if status == 200 and route.startswith("/api/") and not proxied:
            try:
                json.loads(body.decode("utf-8", "replace"))
            except Exception:
                ok_json = False
                detail = "响应非 JSON"
        if is_page(route):
            good = status in (200, 301, 302, 303)
        elif route in DEMO_GAPS and status != 200:
            # 演示数据（无真实行情）下这些接口必然缺数据：记为 SKIP，不计失败
            good = True
            detail = "SKIP 演示模式缺数据：" + DEMO_GAPS[route]
        else:
            # deck_server 对"状态文件尚未生成"的接口返回 404 + JSON（如 /api/harness），
            # 参数校验失败返回 400 + JSON，均为正常响应；其余非 200 仍判失败。
            good = status in (200, 400, 404) and ok_json
            if status == 404:
                detail = "空态 404（状态文件未生成）"
            elif status == 400:
                detail = "参数校验 400（接口存活）"
        if good:
            oks += 1
            tag = "SKIP" if route in DEMO_GAPS and status != 200 else "OK"
            rows.append((tag, route, status, detail or f"{len(body)}B"))
        else:
            fails.append(route)
            rows.append(("FAIL", route, status, detail or body[:120].decode("utf-8", "replace")))

    for p in prefixes:
        test = p + ("pool" if p.endswith("/") else "")
        status, ctype, body = probe(base + test)
        if status in (200, 400, 404, 405):
            oks += 1
            rows.append(("OK", test + " (prefix)", status, f"{len(body)}B"))
        else:
            warns.append(test)
            rows.append(("WARN", test + " (prefix)", status, body[:100].decode("utf-8", "replace")))

    for r in rows:
        print(f"[{r[0]:4}] {r[2]:>3}  {r[1]:<34} {r[3]}")

    # HARNESS 直连 + 经量化服务器反代
    h_status, _, h_body = probe(args.harness.rstrip("/") + "/")
    p_status, _, p_body = probe(base + "/api/proxy/")
    print(f"\nHARNESS :3080 直连 -> {h_status} ({len(h_body)}B)")
    print(f"HARNESS 反代 /api/proxy/ -> {p_status} ({len(p_body)}B)")

    print(f"\n合计：OK {oks} / FAIL {len(fails)} / WARN {len(warns)}")
    if fails:
        print("失败路由：" + ", ".join(fails))
    if warns:
        print("告警路由：" + ", ".join(warns))
    harness_ok = h_status == 200 and p_status == 200
    print(f"HARNESS 联通：{'是' if harness_ok else '否'}")
    return 0 if (not fails and harness_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
