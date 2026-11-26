# -*- coding: utf-8 -*-
"""估值快照（PE/PB/总市值）→ finance.db.valuation —— 免 token 方案（百度股市通）。

背景：项目的估值两处入口：
  1) `factors/opportunities/scan.py::load_valuation()` —— 只认作者自建备用服务器
     （`data.tushare_backup.url + api_key`，HTTP /daily-basic），本机没有该地址；官方
     Tushare `daily_basic` 又需要 2000 积分（免费 120 分不可用）。
  2) `finance.db.valuation` 表 —— `tech_pitch_v3` 读 total_mv 做市值分档，之前无人写入。

本脚本用百度估值（akshare `stock_zh_valuation_baidu`，实测可用）逐股取
  总市值(亿) / 市盈率(TTM) / 市净率
写入 `finance.db.valuation`，字段口径对齐项目：
  total_mv = 亿元 × 10000（项目按"万元"存，`scan` 里 /10000 还原成亿）
  pe_ttm / pb 原值；circ_mv 暂无（百度不提供流通市值）

之后 `scan.load_valuation()` 会优先读本地表（已同步改造），value / quality_gap 类即可触发。

用法：
    python scripts/pull_valuation_baidu.py --limit 20      # 小样本验证
    python scripts/pull_valuation_baidu.py                 # 全量（约 15–20 分钟，断点续传）
    python scripts/pull_valuation_baidu.py --workers 6
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

FIN_DB = BASE / "data" / "cache" / "finance.db"
LOG_FILE = BASE / "logs" / "pull_valuation.log"
FAIL_FILE = BASE / "logs" / "pull_valuation_failed.txt"

_print_lock = threading.Lock()


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with _print_lock:
        print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def init_db():
    con = sqlite3.connect(str(FIN_DB))
    con.execute("""CREATE TABLE IF NOT EXISTS valuation (
        trade_date TEXT, code TEXT, pe REAL, pe_ttm REAL, pb REAL, ps_ttm REAL,
        dv_ttm REAL, total_mv REAL, circ_mv REAL, source TEXT,
        PRIMARY KEY (trade_date, code))""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_val_date ON valuation (trade_date, code)")
    con.commit()
    con.close()


def _last(ind: str, code6: str):
    """取该指标最新一条 (date, value)；失败/空 → (None, None)"""
    import akshare as ak
    df = ak.stock_zh_valuation_baidu(symbol=code6, indicator=ind, period="近一年")
    if df is None or not len(df):
        return None, None
    row = df.iloc[-1]
    d = str(row["date"])[:10]
    try:
        v = float(row["value"])
    except Exception:
        return d, None
    return d, v


def fetch_one(full_code: str):
    code6 = full_code.split(".")[0]
    d_mv, mv_yi = _last("总市值", code6)
    _, pe_ttm = _last("市盈率(TTM)", code6)
    _, pb = _last("市净率", code6)
    if mv_yi is None and pe_ttm is None and pb is None:
        return None
    date = d_mv or datetime.now().strftime("%Y-%m-%d")
    return {
        "trade_date": date, "code": full_code,
        "pe_ttm": pe_ttm, "pb": pb,
        "total_mv": (mv_yi * 10000.0) if mv_yi is not None else None,
        "circ_mv": None, "source": "baidu",
    }


def universe(limit=None):
    con = sqlite3.connect("file:" + str(BASE / "data" / "cache" / "stock_basic.db") + "?mode=ro", uri=True)
    codes = [r[0] for r in con.execute("SELECT code FROM stock_basic WHERE status='1' ORDER BY code")]
    con.close()
    return codes[:limit] if limit else codes


def done_codes(date_prefix: str):
    con = sqlite3.connect(str(FIN_DB))
    rows = {r[0] for r in con.execute(
        "SELECT code FROM valuation WHERE trade_date LIKE ?", (date_prefix + "%",))}
    con.close()
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    init_db()
    # 断点续传的基准日用"数据日"（bars.db 最新交易日），而不是系统日期——
    # 百度估值返回的是最近交易日的快照，跨零点跑时用系统日期会重复拉全量。
    today = None
    try:
        _b = sqlite3.connect("file:" + str(BASE / "data" / "cache" / "bars.db") + "?mode=ro", uri=True)
        today = _b.execute("SELECT MAX(date) FROM daily_bar WHERE adjust='qfq'").fetchone()[0]
        _b.close()
    except Exception:
        pass
    today = today or datetime.now().strftime("%Y-%m-%d")
    codes = universe(args.limit or None)
    done = set() if args.force else done_codes(today)
    todo = [c for c in codes if c not in done]
    log(f"股票 {len(codes)} 只，今日已有 {len(done)} 只，待拉 {len(todo)} 只，并发 {args.workers}")

    con = sqlite3.connect(str(FIN_DB))
    ok = 0
    empty, failed = [], []
    t0 = time.time()
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, c): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            code = futs[fut]
            try:
                row = fut.result()
            except Exception as e:
                failed.append((code, f"{type(e).__name__}: {str(e)[:100]}"))
                row = None
            if row is None:
                empty.append(code)
            else:
                with lock:
                    con.execute(
                        "INSERT OR REPLACE INTO valuation "
                        "(trade_date, code, pe, pe_ttm, pb, ps_ttm, dv_ttm, total_mv, circ_mv, source) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (row["trade_date"], row["code"], None, row["pe_ttm"], row["pb"],
                         None, None, row["total_mv"], row["circ_mv"], row["source"]))
                    con.commit()
                ok += 1
            if i % 100 == 0 or i == len(todo):
                el = time.time() - t0
                rate = i / el if el else 0
                log(f"进度 {i}/{len(todo)} | 成功 {ok} 空 {len(empty)} 失败 {len(failed)} | "
                    f"{rate:.1f} 只/s | ETA {(len(todo) - i) / rate / 60 if rate else 0:.0f} 分钟")
    con.close()
    log(f"== 完成 == 成功 {ok} 只，空 {len(empty)}，失败 {len(failed)}，耗时 {(time.time()-t0)/60:.1f} 分钟")
    if empty or failed:
        with open(FAIL_FILE, "w", encoding="utf-8") as f:
            for c in empty:
                f.write(f"empty\t{c}\n")
            for c, e in failed:
                f.write(f"fail\t{c}\t{e}\n")
        log(f"清单 → {FAIL_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
