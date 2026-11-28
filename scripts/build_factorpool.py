# -*- coding: utf-8 -*-
"""本地构建"因子池"产物（补上开源包缺失的外部工程输出）。

背景：`/factors` 页面（`/api/live/factor_dash`）读的全是作者「因子池」工程的产物：
    data/factorpool/output/factor_manifest_*.json      因子清单（code/name_cn/category/direction/icir_60/status）
    data/factorpool/output/health/health_*.csv         体检（factor/status/icir20/60/120…）
    data/factorpool/output/daily_scores/daily_*.csv    全市场因子分（反向信号/量价共识用）
    data/factorpool/output/crowding_*.json             市场拥挤度（仪表盘）
这些文件不在开源仓库里，也没有生成脚本 → 页面"当前因子/风控/拥挤度"全空。

本脚本用**本仓库自己的数据**算一份最小可用版本（不需要外部因子池工程）：
  · 拥挤度：全市场换手中位数 vs 过去 252 日分位 + 个股换手 80 分位以上只数
  · 因子体检：6 个核心因子（低波/接近高点/20日反转/120日反转/换手均值/换手波动）
    对 5 日前瞻收益的 Rank IC → ICIR20/60/120 → 状态分级
  · 因子清单：按体检结果生成 manifest（含中文名/分类/方向）
  · daily_scores：最新一日全市场因子原始值 + 截面排名（供反向信号/量价共识等下游）

用法：
    python scripts/build_factorpool.py --days 320
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import numpy as np
import pandas as pd

OUT = BASE / "data" / "factorpool" / "output"
BARS = BASE / "data" / "cache" / "bars.db"

# 因子定义：code → (中文名, 分类, 方向, 计算函数(接收 close/volume/turn/amount 面板))
FACTORS = {
    "lowvol_60": {"name": "低波60日", "cat": "低波动", "dir": -1},
    "near_high_250": {"name": "接近52周高点", "cat": "动量", "dir": 1},
    "mom_20": {"name": "20日涨幅(反转)", "cat": "反转", "dir": -1},
    "mom_120": {"name": "120日涨幅(反转)", "cat": "反转", "dir": -1},
    "turn_mean20": {"name": "20日均换手", "cat": "流动性", "dir": -1},
    "turn_std20": {"name": "换手波动20日", "cat": "流动性", "dir": -1},
}
FORWARD_DAYS = 5


def load_panel(days: int):
    con = sqlite3.connect(f"{BARS.resolve().as_uri()}?mode=ro&immutable=1", uri=True, timeout=10)
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM daily_bar WHERE adjust='qfq' ORDER BY date DESC LIMIT ?", (days + 130,))]
    dates = sorted(dates)[-days:]
    q = ("SELECT code, date, close, volume, amount, turn FROM daily_bar "
         f"WHERE adjust='qfq' AND date IN ({','.join('?' * len(dates))})")
    df = pd.read_sql_query(q, con, params=dates)
    con.close()
    if df.empty:
        raise SystemExit("bars.db 无数据")
    close = df.pivot(index="date", columns="code", values="close").sort_index()
    turn = df.pivot(index="date", columns="code", values="turn").sort_index()
    amount = df.pivot(index="date", columns="code", values="amount").sort_index()
    return close.astype(float), turn.astype(float), amount.astype(float)


def build_factors(close: pd.DataFrame, turn: pd.DataFrame) -> dict:
    ret = close.pct_change()
    out = {
        "lowvol_60": ret.rolling(60, min_periods=40).std(),
        "near_high_250": close / close.rolling(250, min_periods=60).max(),
        "mom_20": close / close.shift(20) - 1.0,
        "mom_120": close / close.shift(120) - 1.0,
        "turn_mean20": turn.rolling(20, min_periods=10).mean(),
        "turn_std20": turn.rolling(20, min_periods=10).std(),
    }
    return out


def rank_ic(fpanel: pd.DataFrame, fwd: pd.DataFrame) -> pd.Series:
    """逐日截面 Rank IC（Spearman）。"""
    a = fpanel.rank(axis=1)
    b = fwd.rank(axis=1)
    return a.corrwith(b, axis=1)


def icir(ic: pd.Series, w: int):
    if ic.dropna().shape[0] < max(10, w // 3):
        return None
    roll = ic.rolling(w, min_periods=max(8, w // 3))
    m, s = roll.mean().iloc[-1], roll.std().iloc[-1]
    if m is None or s is None or not np.isfinite(m) or not np.isfinite(s) or s == 0:
        return None
    return round(float(m / s), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=320)
    args = ap.parse_args()

    close, turn, amount = load_panel(args.days)
    if close.empty:
        raise SystemExit("面板为空")
    date = close.index[-1]
    date8 = str(date).replace("-", "")

    # ---------- 1) 因子值 + 前瞻收益 + IC ----------
    fpanels = build_factors(close, turn)
    fwd = close.shift(-FORWARD_DAYS) / close - 1.0
    health_rows, manifest_factors = [], []
    for code, meta in FACTORS.items():
        fp = fpanels[code]
        ic = rank_ic(fp, fwd).dropna()
        ic20, ic60, ic120 = icir(ic, 20), icir(ic, 60), icir(ic, 120)
        ic_mean = round(float(ic.tail(60).mean()), 4) if len(ic) else None
        # 状态：按 |ICIR60| 与方向一致性分级
        status = "数据不足"
        if ic60 is not None and ic_mean is not None:
            expect = meta["dir"] * ic_mean            # 方向正确时为正
            if expect <= 0 and abs(ic60) >= 0.3:
                status = "反向"
            elif abs(ic60) >= 0.5:
                status = "有效"
            elif abs(ic60) >= 0.3:
                status = "弱有效"
            else:
                status = "衰减"
        health_rows.append({
            "test_date": date, "factor": code, "name_cn": meta["name"],
            "n_days": int(ic.shape[0]), "ic_mean60": ic_mean,
            "icir20": ic20, "icir60": ic60, "icir120": ic120,
            "status": status,
        })
        manifest_factors.append({
            "code": code, "name_cn": meta["name"], "category": meta["cat"],
            "direction": meta["dir"], "icir_20": ic20, "icir_60": ic60,
            "icir_120": ic120, "status": status, "usage": "选股/风控参考",
        })

    # ---------- 2) 拥挤度（全市场换手中位数 252 日分位） ----------
    mkt_turn = turn.median(axis=1).dropna()
    pctile = None
    if len(mkt_turn) >= 60:
        cur = float(mkt_turn.iloc[-1])
        hist = mkt_turn.tail(252)
        pctile = float((hist <= cur).mean())
    last_turn = turn.iloc[-1].dropna()
    n_crowded = int((last_turn > last_turn.quantile(0.8)).sum()) if len(last_turn) else 0
    zone = ("过热" if (pctile or 0) > 0.8 else "偏热" if (pctile or 0) > 0.6
            else "正常" if (pctile or 0) > 0.3 else "冷清")
    crowd = {
        "date": str(date),
        "crowding_mkt": round(float(mkt_turn.iloc[-1]), 2) if len(mkt_turn) else None,
        "crowding_pctile_252": round(pctile, 4) if pctile is not None else None,
        "zone": zone, "n_crowded_stocks": n_crowded,
        "definition": "全市场换手中位数的 252 日分位；n_crowded=当日换手处于截面 80 分位以上的个股数",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # ---------- 3) 落盘 ----------
    (OUT / "health").mkdir(parents=True, exist_ok=True)
    (OUT / "daily_scores").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(health_rows).to_csv(OUT / "health" / f"health_{date8}.csv",
                                     index=False, encoding="utf-8")
    (OUT / f"factor_manifest_{date8}.json").write_text(json.dumps({
        "date": str(date), "health_date": str(date),
        "factors": manifest_factors,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"crowding_{date8}.json").write_text(
        json.dumps(crowd, ensure_ascii=False, indent=1), encoding="utf-8")

    # daily_scores：最新一日因子原始值 + 截面排名（下游反向信号/量价共识可能用）
    latest = pd.DataFrame({c: fpanels[c].iloc[-1] for c in FACTORS}).dropna(how="all")
    latest.index.name = "code"
    for c in FACTORS:
        latest[f"{c}_rank"] = latest[c].rank(pct=True)
    latest["date"] = str(date)
    latest.reset_index().to_csv(OUT / "daily_scores" / f"daily_{date8}.csv",
                                index=False, encoding="utf-8")

    print(f"日期 {date}｜因子 {len(FACTORS)} 个｜拥挤度分位 {crowd['crowding_pctile_252']}（{zone}）"
          f"｜拥挤个股 {n_crowded} 只")
    for r in health_rows:
        print(f"  {r['factor']:<14} ICIR20={r['icir20']} ICIR60={r['icir60']} "
              f"ICIR120={r['icir120']} → {r['status']}")
    print(f"输出目录: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
