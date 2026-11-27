# -*- coding: utf-8 -*-
"""scripts/daily_run.py — 盘后日更一条命令（可挂 Windows 计划任务）。

串起本机实测过的步骤（含真实耗时，2026-11-26）：

  1. 增量日线（腾讯源，回看 5 天）        ≈ 3–4 分钟   （--skip-fetch 跳过）
  2. 沪深300 指数刷新                      < 1 秒
  3. 宏观缓存（社融/国债）                 ≈ 4 秒
  4. 五福轮动 parquet 缓存重建             ≈ 2 秒
  5. 机会扫描 --pitch（全市场 5224 只）    ≈ 22 分钟   （--skip-scan 跳过）
  6. Pitch v2 Deck                        ≈ 1 秒
  7. 短线科技池 tech_pitch_v3             ≈ 13 秒
  8. 日报（dry-run，不写池）              ≈ 3 秒
  9. 五福轮动信号                         ≈ 3 秒
 10. ETF 映射                             ≈ 1 分钟    （--skip-etf 跳过）
 11. 时间戳文件归档（保留最新 5 份）        < 1 秒
 12. 部署自检（121 条路由 + HARNESS）      ≈ 1–2 分钟  （--skip-verify 跳过）

合计约 28–32 分钟。日志：logs/daily_run_<ts>.log，摘要：logs/daily_run_<ts>_summary.json。

用法：
    python scripts/daily_run.py                  # 全量日更
    python scripts/daily_run.py --skip-etf       # 跳过 ETF（ETF 可每周跑）
    python scripts/daily_run.py --skip-fetch --skip-scan   # 只跑轻量步骤
    python scripts/daily_run.py --scheduled      # 计划任务模式（隐藏控制台窗口）
"""
import argparse
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
LOGS = BASE / "logs"
PY = sys.executable

try:                                  # 计划任务里不弹黑框
    import ctypes
    _h = ctypes.windll.kernel32.GetConsoleWindow()
    if _h:
        ctypes.windll.user32.ShowWindow(_h, 0)
except Exception:
    pass

# (名称, [脚本相对路径, 参数...], 超时秒, 关键步骤?)
STEPS_FULL = [
    ("增量日线",      ["scripts/pull_real_data.py", "--incremental", "--days-back", "5"],  1200, True),
    # 兜底修复：任何来源写入的 preclose/pct_chg 空值（会让涨停/动量/振幅因子失真）
    ("涨跌幅修复",    ["scripts/fix_preclose_pctchg.py"],                                   300, False),
    # ★ST 打标必须在增量日线之后：增量写入的 is_st 一律为 0（腾讯源无该字段），
    #   会覆盖掉前一日已打的标记 → 不补这步，当天的 ST 过滤与风控兜底全部失效
    #   （实测漏掉后池子里出现「ST八菱」）。
    ("ST 标记",       ["scripts/mark_st_current.py"],                                      120, False),
    # 估值快照（免费源，PE/PB/总市值）→ finance.db.valuation；不跑则 value/quality_gap 类与
    # 个股诊断的估值维度全部缺数据（scan.load_valuation 优先读这张表）
    ("估值快照",      ["scripts/pull_valuation_baidu.py", "--workers", "6"],               900, False),
    ("沪深300指数",   ["scripts/load_index.py"],                                            300, False),
    ("宏观缓存",      ["data/fetch_macro_cache.py"],                                        300, False),
    ("五福缓存",      ["scripts/build_wufu_cache.py"],                                      300, False),
    ("机会扫描",      ["factors/opportunities/scan.py", "--pitch"],                       2400, True),
    ("Pitch v2",     ["factors/opportunities/pitch_v2.py"],                               600, True),
    ("短线科技池",    ["factors/opportunities/tech_pitch_v3.py"],                          900, False),
    ("三层池",        ["strategy/pool_layers.py"],                                         300, False),
    ("择时系统",      ["factors/policy/timing_system.py"],                                 300, False),
    ("远期池 T+1",    ["factors/opportunities/pitch_track.py"],                             600, False),
    ("止损监测",      ["risk/position_stop_check.py"],                                      600, False),
    ("日报",         ["data/daily_report_auto.py", "--dry-run"],                           300, False),
    ("五福轮动",      ["factors/policy/global_rotation.py"],                                300, False),
    ("ETF 映射",     ["etf/etf_map.py"],                                                   900, False),
    ("文件归档",      ["data/logs_archive.py"],                                             180, False),
    ("部署自检",      ["scripts/_smoke_deploy.py"],                                         600, False),
]
# 参数 → 要跳过的步骤名
SKIP_FLAGS = {"--skip-fetch": {"增量日线", "ST 标记"}, "--skip-scan": {"机会扫描", "Pitch v2"},
              "--skip-etf": {"ETF 映射"}, "--skip-verify": {"部署自检"},
              "--skip-valuation": {"估值快照"}}


def main() -> int:
    ap = argparse.ArgumentParser()
    for f in SKIP_FLAGS:
        ap.add_argument(f, action="store_true", help=f"跳过：{'/'.join(sorted(SKIP_FLAGS[f]))}")
    ap.add_argument("--scheduled", action="store_true", help="计划任务模式（仅影响提示语）")
    ap.add_argument("--timeout-scale", type=float, default=1.0, help="超时倍数（慢机器可调大）")
    args = ap.parse_args()

    skip = set()
    for f, names in SKIP_FLAGS.items():
        if getattr(args, f.replace("--", "").replace("-", "_")):
            skip |= names
    steps = [s for s in STEPS_FULL if s[0] not in skip]

    LOGS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOGS / f"daily_run_{ts}.log"
    summary_path = LOGS / f"daily_run_{ts}_summary.json"

    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"          # 子脚本里有 emoji print，GBK 控制台会崩
    env["PYTHONIOENCODING"] = "utf-8"

    def log(msg: str):
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
        print(line, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    log(f"=== 日更开始（{len(steps)} 步，跳过 {sorted(skip) or '无'}） ===")
    results, failed = [], []
    t_all = time.time()

    for name, argv, timeout, critical in steps:
        script = BASE / argv[0]
        if not script.exists():
            log(f"▶ {name} ... [跳过] 脚本不存在：{argv[0]}")
            results.append({"step": name, "status": "missing", "sec": 0})
            if critical:
                failed.append(name)
            continue
        cmd = [PY, "-X", "utf8", str(script), *argv[1:]]
        t0 = time.time()
        log(f"▶ {name} ...")
        try:
            r = subprocess.run(cmd, cwd=str(BASE), env=env, capture_output=True,
                               timeout=timeout * args.timeout_scale)
            out = (r.stdout or b"").decode("utf-8", "replace")
            err = (r.stderr or b"").decode("utf-8", "replace")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(out[-8000:])
                if err.strip():
                    f.write("\n[stderr]\n" + err[-4000:])
            sec = time.time() - t0
            ok = (r.returncode == 0)
            tail = ""
            for ln in reversed([x for x in out.splitlines() if x.strip()]):
                tail = ln.strip()[:150]
                break
            status = "ok" if ok else "fail"
            log(f"  {'✓' if ok else '✗'} {name} 完成 ({sec:.0f}s) | {tail}")
            results.append({"step": name, "status": status, "sec": round(sec, 1),
                            "rc": r.returncode, "tail": tail})
            if not ok:
                failed.append(name)
        except subprocess.TimeoutExpired:
            sec = time.time() - t0
            log(f"  ✗ {name} 超时（>{timeout * args.timeout_scale:.0f}s）")
            results.append({"step": name, "status": "timeout", "sec": round(sec, 1)})
            failed.append(name)
        except Exception as e:
            log(f"  ✗ {name} 异常: {type(e).__name__}: {e}")
            results.append({"step": name, "status": "error", "sec": 0, "error": str(e)[:200]})
            failed.append(name)
            traceback.print_exc()

    total_min = (time.time() - t_all) / 60
    status = "ok" if not failed else "partial"
    log(f"=== 日更结束（{status}）总耗时 {total_min:.1f} 分钟，失败步骤：{failed or '无'} ===")

    import json
    summary = {"ts": ts, "status": status, "total_min": round(total_min, 1),
               "skipped": sorted(skip), "failed": failed,
               "critical_failed": [n for n in failed if n in {s[0] for s in STEPS_FULL if s[3]}],
               "steps": results, "log": log_path.name}
    try:
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"摘要 → {summary_path.name}")
    except Exception as e:
        log(f"摘要写入失败: {e}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
