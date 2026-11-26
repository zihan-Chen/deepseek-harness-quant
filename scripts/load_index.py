# -*- coding: utf-8 -*-
"""载入沪深300指数日线（Regime 择时基准，code=SH.000300, adjust=none）。

项目自带 data/fetch_index_daily.py 走 baostock（本机单只 3–11 秒、偶发断连），
这里改用腾讯/新浪指数接口一次拉全历史，写入同一张 daily_bar（adjust='none'）。
"""
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pandas as pd

from data.cache import DailyCache

CODE = "SH.000300"
START = "2019-01-01"


def fetch_sina():
    """指数日线：akshare 的接口名在不同版本间改过（stock_zh_index_daily →
    index_zh_daily_sina → index_zh_daily_tx），这里按可用性动态挑选，避免绑死单个版本。"""
    import akshare as ak
    for name, kw in (("index_zh_daily_sina", {"symbol": "sh000300"}),
                     ("stock_zh_index_daily", {"symbol": "sh000300"}),
                     ("index_zh_daily_tx", {"symbol": "sh000300"})):
        fn = getattr(ak, name, None)
        if fn is None:
            continue
        try:
            df = fn(**kw)
        except Exception as e:
            print(f"  {name} 失败: {type(e).__name__}: {str(e)[:100]}")
            continue
        if df is not None and not df.empty:
            print(f"  数据源: {name}，{len(df)} 行，列 {list(df.columns)}")
            df["date"] = df["date"].astype(str)
            return df
    return None


def main() -> int:
    t0 = time.time()
    raw = fetch_sina()
    if raw is None or raw.empty:
        print("指数数据为空")
        return 1
    df = raw.copy()
    df = df[df["date"] >= START].reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "amount" not in df.columns:
        df["amount"] = None
    df["preclose"] = df["close"].shift(1)
    df["pct_chg"] = df["close"] / df["preclose"] - 1.0
    df["turn"] = None
    df["is_st"] = 0
    df["code"] = CODE

    cache = DailyCache()
    n = cache.put_daily(CODE, df[["date", "code", "open", "high", "low", "close", "preclose",
                                  "volume", "amount", "turn", "pct_chg", "is_st"]],
                        adjust="none", source="akshare")
    meta = cache.get_meta(CODE, "none")
    print(f"沪深300: 写入 {n} 行（{time.time()-t0:.1f}s）→ {meta.get('start_date')} ~ "
          f"{meta.get('end_date')}，库内累计 {meta.get('rows')} 行")
    print(df.tail(2)[["date", "close", "pct_chg"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
