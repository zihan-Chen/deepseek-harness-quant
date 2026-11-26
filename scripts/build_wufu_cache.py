# -*- coding: utf-8 -*-
"""构建「五福轮动」所需的两个 parquet 缓存（项目仓库里没有这两个外部产物）。

`factors/policy/global_rotation.py` 读：
    data/factorpool/output/cache/wufu_idx.parquet   4 指数收盘（沪深300/中小综指/创业板指/中证A500）
    data/factorpool/output/cache/wufu_etf.parquet   9 只全球 ETF 代理收盘
这两个文件原是作者「因子池」工程的产物，开源包里没有，且列名曾 GBK 损坏 →
直接表现为 `/api/live/wufu_rotation` 报 "Unable to find a usable engine ... pyarrow"。

本脚本用新浪免费接口重建（免 token），列名写清楚（不再依赖位置推断）：
    指数  sh000300 沪深300 / sz399005 中小综指 / sz399006 创业板指 / sh000510 中证A500
    ETF   sh510300 沪深300 / sh518880 黄金 / sh513100 纳指 / sh513500 标普500 / sh513520 日经
          sh513030 德国 / sh512400 有色 / sz159985 豆粕 / sh518800 黄金2

用法：python scripts/build_wufu_cache.py [--refresh]
"""
import argparse
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import pandas as pd

CACHE_DIR = BASE / "data" / "factorpool" / "output" / "cache"

IDX_MAP = {
    "沪深300": "sh000300",
    "中小综指": "sz399005",
    "创业板指": "sz399006",
    "中证A500": "sh000510",
}
ETF_MAP = {
    "沪深300": "sh510300",
    "黄金": "sh518880",
    "纳指": "sh513100",
    "标普500": "sh513500",
    "日经": "sh513520",
    "德国": "sh513030",
    "有色": "sh512400",
    "豆粕": "sz159985",
    "黄金2": "sh518800",
}


def _series(symbol: str, kind: str) -> pd.Series:
    import akshare as ak
    if kind == "index":
        df = ak.index_zh_daily_sina(symbol=symbol)
    else:
        df = ak.fund_etf_hist_sina(symbol=symbol)
    if df is None or df.empty:
        raise RuntimeError("空数据")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"].astype(str))
    s = pd.Series(pd.to_numeric(df["close"], errors="coerce").values,
                  index=df["date"].values, name=symbol).dropna()
    return s


def build(mapping: dict, kind: str, out: Path) -> pd.DataFrame:
    cols = {}
    for name, sym in mapping.items():
        t0 = time.time()
        try:
            cols[name] = _series(sym, kind)
            print(f"  {name:8s} {sym:10s} {len(cols[name]):5d} 行 {time.time()-t0:.1f}s")
        except Exception as e:
            print(f"  {name:8s} {sym:10s} 失败: {type(e).__name__}: {str(e)[:80]}")
    if not cols:
        raise SystemExit(f"{kind} 全部拉取失败")
    df = pd.DataFrame(cols).sort_index().ffill()
    df.index.name = "date"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out)
    print(f"  → {out}（{df.shape[0]} 行 × {df.shape[1]} 列，"
          f"{df.index.min():%Y-%m-%d} ~ {df.index.max():%Y-%m-%d}）")
    return df


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="已存在也重建（默认覆盖，参数保留语义）")
    args = ap.parse_args()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("1) 指数缓存 wufu_idx.parquet")
    build(IDX_MAP, "index", CACHE_DIR / "wufu_idx.parquet")
    print("2) ETF 缓存 wufu_etf.parquet")
    build(ETF_MAP, "etf", CACHE_DIR / "wufu_etf.parquet")
    print("完成。下一步：python factors/policy/global_rotation.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
