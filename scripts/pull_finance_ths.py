# -*- coding: utf-8 -*-
"""财报数据补拉（同花顺 `stock_financial_abstract`，免 token）→ finance.db + finance_quality.db。

为什么不用 data/fetcher_finance.py：
  它调 `stock_financial_abstract_ths`（akshare 1.20.46 起改名/改结构，本机 1.20.70 已无此函数），
  且新的 `stock_financial_abstract` 是"指标 × 报告期"的宽表（原来是长表）。

本脚本做的事：
  1) 宽表 → 长表，复用项目自带 `data.fetcher_finance.parse_finance()` 计算累计/单季/单季同比，
     写入 finance.db.finance_report（net_profit/revenue 单位亿元，与项目口径一致）；
  2) 同时抽 5 个质量比率写入 finance_quality.db.quality
     （roe_avg / gp_margin / np_margin / current_ratio / liability_to_asset / cfo_to_np / cfo_to_or）。

表结构完全沿用项目原有 schema，消费方（factors/opportunities/scan.py、risk/beneish.py 等）无需改动。

用法：
    python scripts/pull_finance_ths.py --limit 20     # 小样本
    python scripts/pull_finance_ths.py                # 全量（约 25–40 分钟，断点续传）
    python scripts/pull_finance_ths.py --workers 6
"""
import argparse
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pandas as pd

from data.fetcher_finance import parse_finance

FIN_DB = BASE / "data" / "cache" / "finance.db"
QD_DB = BASE / "data" / "cache" / "finance_quality.db"
LOG_FILE = BASE / "logs" / "pull_finance.log"
FAIL_FILE = BASE / "logs" / "pull_finance_failed.txt"
PERIOD_MIN = "2019-03-31"
MIN_PERIODS_TO_SKIP = 6

# 宽表指标名 → 长表列名（与 fetcher_finance.parse_finance 的期望列名对齐）
ABSTRACT_IND = {
    "归母净利润": "净利润",
    "营业总收入": "营业总收入",
    "基本每股收益": "每股收益",
    "净资产收益率(ROE)": "净资产收益率",
}
# 宽表指标名 → quality 列名（按顺序取第一个命中的）
QUALITY_IND = [
    ("净资产收益率_平均", "roe_avg"),
    ("净资产收益率(ROE)", "roe_avg"),
    ("毛利率", "gp_margin"),
    ("销售净利率", "np_margin"),
    ("流动比率", "current_ratio"),
    ("资产负债率", "liability_to_asset"),
    ("经营活动净现金/归属母公司的净利润", "cfo_to_np"),
    ("经营性现金净流量/营业总收入", "cfo_to_or"),
]
# 同花顺返回百分数的字段（入库前 ÷100 转成项目约定的小数）：
#   risk/stock_risk._check_row 的脏数据闸门是 gp>1.0/liab>1.5、beneish 以 cfo_to_np>=1.0 判断，
#   stock_check 显示时又 *100 —— 存百分数会让这些下游全部失真（2026-11-26 实测踩坑）。
#   cfo_to_np / cfo_to_or 本来就是倍数/小数（中位数 1.41/0.13），current_ratio 是倍数，均不转换。
PCT_TO_DEC = ("roe_avg", "gp_margin", "np_margin", "liability_to_asset")
QUALITY_COLS = ["roe_avg", "gp_margin", "np_margin", "current_ratio",
                "liability_to_asset", "cfo_to_np", "cfo_to_or"]

_print_lock = threading.Lock()


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with _print_lock:
        print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _num(v):
    try:
        f = float(str(v).replace(",", ""))
        return None if f != f else f          # NaN → None
    except Exception:
        return None


def init_dbs():
    con = sqlite3.connect(str(FIN_DB))
    con.execute("""CREATE TABLE IF NOT EXISTS finance_report (
        code TEXT, period TEXT, net_profit REAL, revenue REAL,
        sq_net_profit REAL, sq_net_yoy REAL, sq_revenue REAL, sq_rev_yoy REAL,
        eps REAL, roe REAL, source TEXT, PRIMARY KEY (code, period))""")
    con.commit()
    con.close()
    con = sqlite3.connect(str(QD_DB))
    con.execute("""CREATE TABLE IF NOT EXISTS quality (
        code TEXT, period TEXT, roe_avg REAL, gp_margin REAL, np_margin REAL,
        current_ratio REAL, liability_to_asset REAL, cfo_to_np REAL, cfo_to_or REAL,
        pub_date TEXT, PRIMARY KEY(code, period))""")
    con.commit()
    con.close()


def fetch_one(code6: str):
    """→ (finance_rows, quality_rows)"""
    import warnings
    warnings.filterwarnings("ignore")
    import akshare as ak

    wide = ak.stock_financial_abstract(symbol=code6)
    if wide is None or wide.empty:
        return [], []
    if "指标" not in wide.columns:
        return [], []
    wide = wide.drop_duplicates(subset=["指标"], keep="first").set_index("指标")
    periods = sorted([c for c in wide.columns if str(c).isdigit() and len(str(c)) == 8])
    periods = [p for p in periods
               if f"{p[:4]}-{p[4:6]}-{p[6:]}" >= PERIOD_MIN]

    long_rows, q_rows = [], []
    for p in periods:
        period = f"{p[:4]}-{p[4:6]}-{p[6:]}"
        rec = {"报告期": period}
        for ind, col in ABSTRACT_IND.items():
            rec[col] = wide.loc[ind, p] if ind in wide.index else None
        long_rows.append(rec)

        q = {"code": code6, "period": period}
        for ind, col in QUALITY_IND:
            if col in q and q[col] is not None:
                continue
            if ind in wide.index:
                q[col] = _num(wide.loc[ind, p])
            else:
                q.setdefault(col, None)
        q_rows.append(q)

    fin_rows = parse_finance(code6, pd.DataFrame(long_rows)) if long_rows else []
    # 营收/净利保持"亿元"；roe 从百分数转小数（项目约定 finance_report.roe 为小数）
    fin_rows = [(c, p, net, rev, sqn, sqny, sqr, sqry, eps,
                 (roe / 100.0 if roe is not None else None), src)
                for (c, p, net, rev, sqn, sqny, sqr, sqry, eps, roe, src) in fin_rows]
    for r in q_rows:
        for k in PCT_TO_DEC:
            if r.get(k) is not None:
                r[k] = r[k] / 100.0
    q_out = [(code6, r["period"], *[r.get(c) for c in QUALITY_COLS], None) for r in q_rows]
    return fin_rows, q_out


def load_codes(limit=None):
    con = sqlite3.connect("file:" + str(BASE / "data" / "cache" / "bars.db") + "?mode=ro", uri=True)
    codes = [r[0] for r in con.execute(
        "SELECT DISTINCT code FROM daily_bar WHERE code NOT LIKE 'SH.%' AND code NOT LIKE 'sh.%'")]
    con.close()
    codes = sorted({c.split(".")[0] for c in codes})
    return codes[:limit] if limit else codes


def done_codes():
    con = sqlite3.connect(str(FIN_DB))
    rows = set(r[0] for r in con.execute(
        "SELECT code FROM finance_report GROUP BY code HAVING COUNT(*)>=?", (MIN_PERIODS_TO_SKIP,)))
    con.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    init_dbs()
    codes = load_codes(args.limit or None)
    done = set() if args.force else done_codes()
    todo = [c for c in codes if c not in done]
    log(f"股票 {len(codes)} 只，已完成 {len(done)} 只，待拉 {len(todo)} 只，并发 {args.workers}")

    t0 = time.time()
    ok = n_fin = n_q = 0
    empty, failed = [], []
    fin_con = sqlite3.connect(str(FIN_DB))
    qd_con = sqlite3.connect(str(QD_DB))
    write_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, c): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            code = futs[fut]
            try:
                fin_rows, q_rows = fut.result()
            except Exception as e:
                failed.append((code, f"{type(e).__name__}: {str(e)[:110]}"))
                fin_rows, q_rows = [], []
            if not fin_rows:
                empty.append(code)
            else:
                with write_lock:
                    fin_con.executemany(
                        "INSERT OR REPLACE INTO finance_report VALUES (?,?,?,?,?,?,?,?,?,?,?)", fin_rows)
                    qd_con.executemany(
                        "INSERT OR REPLACE INTO quality VALUES (?,?,?,?,?,?,?,?,?,?)", q_rows)
                    fin_con.commit()
                    qd_con.commit()
                ok += 1
                n_fin += len(fin_rows)
                n_q += len(q_rows)
            if i % 100 == 0 or i == len(todo):
                el = time.time() - t0
                rate = i / el if el else 0
                log(f"进度 {i}/{len(todo)} | 成功 {ok} 空 {len(empty)} 失败 {len(failed)} | "
                    f"{rate:.2f} 只/s | 财报 {n_fin} 行 / 质量 {n_q} 行 | "
                    f"ETA {(len(todo) - i) / rate / 60 if rate else 0:.0f} 分钟")

    fin_con.close()
    qd_con.close()
    log(f"== 完成 == 成功 {ok} 只，空 {len(empty)}，失败 {len(failed)}，"
        f"耗时 {(time.time() - t0) / 60:.1f} 分钟")
    if empty or failed:
        with open(FAIL_FILE, "w", encoding="utf-8") as f:
            for c in empty:
                f.write(f"empty\t{c}\n")
            for c, e in failed:
                f.write(f"fail\t{c}\t{e}\n")
        log(f"失败/空清单 → {FAIL_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
