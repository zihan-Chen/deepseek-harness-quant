# -*- coding: utf-8 -*-
"""真实 A 股日线拉取（腾讯源，前复权）——本机部署用补充脚本。

为什么不用项目自带的 bulk_loader.py（baostock 主源）：
  实测本机到 baostock 单只 3–11 秒（并发后更慢，8 只样本耗时 5 分钟），
  5224 只全量需 8–10 小时；东财 push2 接口对本机 IP 限流（Push2RateLimitError），
  故改用腾讯 `stock_zh_a_hist_tx`：单只约 0.5 秒、支持前复权、volume/amount 与
  baostock 完全一致（实测 600036：成交量、成交额逐日相同，最新收盘价相同）。

口径与校验（实测记录，2026-11-25）：
  - 复权：adjust="qfq"，最新交易日收盘价与 baostock 一致（差 0），
    历史段因两家除权因子基准不同有差异（600036 最大 5.70 元）→ 同一只票内部收益口径自洽；
    批量入库统一走本脚本，不与 baostock 样本混用。
  - 单位：volume=股、amount=元（与 baostock 相同，写入 source="akshare" 不触发千元/手换算）
  - 换手率：腾讯 turnover 是小数（0.0027 = 0.27%），入库乘 100 对齐 bars.db 的 turn(%)
  - is_st：本脚本置 0（腾讯无 ST 标记）；如需历史 ST，用 data/fix_st_flags.py（baostock，1–2 小时）

用法：
    python scripts/pull_real_data.py                # 全量（5224 只，断点续传）
    python scripts/pull_real_data.py --limit 50     # 小样本
    python scripts/pull_real_data.py --workers 6 --start 2019-01-01
    python scripts/pull_real_data.py --include-delisted   # 含退市（342 只，防幸存者偏差）
"""
import argparse
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pandas as pd

from data.cache import DailyCache

LOG_FILE = BASE / "logs" / "pull_real.log"
FAIL_FILE = BASE / "logs" / "pull_real_failed.txt"
STOCK_DB = BASE / "data" / "cache" / "stock_basic.db"

_print_lock = threading.Lock()


def log(msg: str):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with _print_lock:
        print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def universe(include_delisted: bool, limit=None):
    import sqlite3
    con = sqlite3.connect(str(STOCK_DB))
    try:
        where = "status IN ('1','0')" if include_delisted else "status='1'"
        codes = [r[0] for r in con.execute(
            f"SELECT code FROM stock_basic WHERE {where} ORDER BY code")]
    finally:
        con.close()
    return codes[:limit] if limit else codes


def _to_tx_symbol(code: str) -> str:
    num, mkt = code.split(".")
    return ("sh" if mkt == "SH" else "sz") + num


def fetch_one(code: str, start: str, end: str):
    """拉取单只前复权日线 → 标准化 DataFrame（不含写库）。

    ★2026-11-27 修复（关键）：原实现先按 start 切片再算 preclose，窗口**第一行**必然
    shift 成 NaN → 写库时 INSERT OR REPLACE 把库里原本正确的前一日行覆盖成
    preclose/pct_chg=NULL（实测 11-20、11-23 两天几乎全市场 pct_chg 变 NULL，
    涨停次数/动量/振幅/反转全失真）。现改为：
      1) 多取 15 个自然日的回看（只为算 preclose）；
      2) 算完 preclose/pct_chg 再切回 [start, end]；
      3) 首行若仍无前收（新股/超长停牌），宁可不写该行，也不要用 NaN 覆盖已有数据。
    """
    import akshare as ak
    sym = _to_tx_symbol(code)
    _lookback = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=15)).strftime("%Y-%m-%d")
    raw = ak.stock_zh_a_hist_tx(
        symbol=sym, start_date=_lookback.replace("-", ""), end_date=end.replace("-", ""),
        adjust="qfq")
    if raw is None or raw.empty:
        return None
    df = raw.rename(columns={"turnover": "turn"}).copy()
    df["date"] = df["date"].astype(str)
    df["turn"] = pd.to_numeric(df["turn"], errors="coerce") * 100.0     # 小数 → %
    for c in ("open", "high", "low", "close", "volume", "amount"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    df["preclose"] = df["close"].shift(1)
    df["pct_chg"] = df["close"] / df["preclose"] - 1.0
    # 切回目标区间；窗口首行（若确实没有前收）丢弃，避免用 NaN 覆盖正确数据
    df = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    df = df[df["preclose"].notna()]
    if df.empty:
        return None
    df["is_st"] = 0
    df["code"] = code.upper()
    return df[["date", "code", "open", "high", "low", "close", "preclose",
               "volume", "amount", "turn", "pct_chg", "is_st"]]


def _latest_bar_date(cache) -> str | None:
    """库内 qfq 最新交易日（增量模式的起点基准）。"""
    import sqlite3
    try:
        uri = f"{Path(cache.db_path).resolve().as_uri()}?mode=ro&immutable=1"
        con = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            return con.execute("SELECT MAX(date) FROM daily_bar WHERE adjust='qfq'").fetchone()[0]
        finally:
            con.close()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2019-01-01")
    ap.add_argument("--end", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--include-delisted", action="store_true")
    ap.add_argument("--force", action="store_true", help="已覆盖的代码也重拉")
    ap.add_argument("--incremental", action="store_true",
                    help="日更增量：只补库内最新交易日之后 / 回看 N 天（实测约 0.2s/只，全市场 3–4 分钟）")
    ap.add_argument("--days-back", type=int, default=5,
                    help="增量模式回看天数（默认 5，覆盖长周末/节假日）")
    args = ap.parse_args()

    cache = DailyCache()
    if args.incremental:
        latest = _latest_bar_date(cache)
        if not latest:
            log("增量模式：库内无 qfq 数据 → 自动退回全量拉取")
        else:
            start_dt = datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=args.days_back)
            args.start = start_dt.strftime("%Y-%m-%d")
            args.force = True          # 增量窗口内一律重拉，避免 covers() 判「已覆盖」而漏掉最新几日
            log(f"增量模式：库内最新 {latest}，回看 {args.days_back} 天 → 从 {args.start} 起补齐")
    codes = universe(args.include_delisted, args.limit or None)
    log(f"股票池 {len(codes)} 只 | 区间 {args.start} ~ {args.end} | 并发 {args.workers} | "
        f"库 {cache.db_path}")

    todo = []
    skipped = 0
    for c in codes:
        if not args.force and cache.covers(c, args.start, args.end, "qfq"):
            skipped += 1
            continue
        todo.append(c)
    log(f"已覆盖跳过 {skipped} 只，待拉 {len(todo)} 只")

    t0 = time.time()
    ok = rows = 0
    empty, failed = [], []
    write_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_one, c, args.start, args.end): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            code = futs[fut]
            try:
                df = fut.result()
            except Exception as e:
                failed.append((code, f"{type(e).__name__}: {str(e)[:120]}"))
                df = None
            else:
                if df is None:
                    empty.append(code)
            if df is not None and not df.empty:
                with write_lock:            # 写库串行，避免 SQLite 锁竞争
                    cache.put_daily(code, df, adjust="qfq", source="akshare")
                ok += 1
                rows += len(df)
            if i % 100 == 0 or i == len(todo):
                el = time.time() - t0
                rate = i / el if el else 0
                eta = (len(todo) - i) / rate / 60 if rate else 0
                log(f"进度 {i}/{len(todo)} | 成功 {ok} 空 {len(empty)} 失败 {len(failed)} | "
                    f"{rate:.1f} 只/s | 已写 {rows} 行 | ETA {eta:.0f} 分钟")

    el = time.time() - t0
    log(f"== 完成 == 成功 {ok} 只 / {rows} 行，空数据 {len(empty)}，失败 {len(failed)}，"
        f"耗时 {el / 60:.1f} 分钟")
    if empty or failed:
        FAIL_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(FAIL_FILE, "w", encoding="utf-8") as f:
            f.write(f"# {datetime.now():%Y-%m-%d %H:%M} 空数据 {len(empty)} / 失败 {len(failed)}\n")
            for c in empty:
                f.write(f"empty\t{c}\n")
            for c, e in failed:
                f.write(f"fail\t{c}\t{e}\n")
        log(f"失败/空清单 → {FAIL_FILE}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
