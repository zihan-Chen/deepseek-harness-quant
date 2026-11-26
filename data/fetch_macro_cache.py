# -*- coding: utf-8 -*-
"""data/fetch_macro_cache.py — 宏观择时数据缓存（社融/国债收益率）

供择时条件池使用：信贷脉冲（社融 12 月滚动）、股债利差（预留）。
数据源：AkShare 免费接口 → data/cache/macro.db（月度表）

用法：python data/fetch_macro_cache.py
"""
import os
import sqlite3
import sys
from pathlib import Path

for k in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
    os.environ.pop(k, None)

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

DB = Path(r"data/cache/macro.db")


def _pick(df, *names):
    """按列名取第一个存在的列（akshare 各版本列名会变，禁止用位置索引）。"""
    for n in names:
        if n in df.columns:
            return n
    return None


def _to_float(v):
    try:
        f = float(str(v).replace(",", ""))
        return None if f != f else f
    except Exception:
        return None


def main():
    import akshare as ak
    con = sqlite3.connect(str(DB))
    con.execute("""CREATE TABLE IF NOT EXISTS social_finance (
        month TEXT PRIMARY KEY, sf_increment REAL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS bond_yield (
        date TEXT PRIMARY KEY, y10 REAL, y2 REAL)""")
    con.commit()

    # 1) 社融增量（月度）★部署修复：macro_china_shrzgm 在 akshare 1.20.42 改名
    #    macro_china_social_financing，且列名从位置索引改为中文列名
    try:
        fn = (getattr(ak, "macro_china_social_financing", None)
              or getattr(ak, "macro_china_shrzgm", None))
        if fn is None:
            raise RuntimeError("当前 akshare 版本无社融接口")
        df = fn()
        c_m = _pick(df, "月份", "月", "month")
        c_v = _pick(df, "社会融资规模增量", "社会融资规模增量(亿元)", "sf_increment")
        if c_m is None or c_v is None:
            raise RuntimeError(f"社融列名变化：{list(df.columns)[:6]}")
        n = 0
        for _, r in df.iterrows():
            m = str(r[c_m]).strip()
            v = _to_float(r[c_v])
            if m and m != "nan" and v is not None:
                con.execute("INSERT OR REPLACE INTO social_finance VALUES (?,?)", (m, v))
                n += 1
        con.commit()
        print(f"社融缓存: {n} 个月（{df[c_m].iloc[-1]} 最新）")
    except Exception as e:
        print(f"社融失败: {str(e)[:120]}")

    # 2) 国债收益率（日频）★部署修复：bond_zh_us_rate 在 akshare 1.20.41 改名
    #    bond_zh_us_yield_em（无 start_date 参数，返回 2010 年至今全量）
    try:
        fn = (getattr(ak, "bond_zh_us_yield_em", None)
              or getattr(ak, "bond_zh_us_rate", None))
        if fn is None:
            raise RuntimeError("当前 akshare 版本无国债收益率接口")
        try:
            df = fn(start_date="20180101")      # 旧接口签名
        except TypeError:
            df = fn()                            # 新接口无参
        c_d = _pick(df, "日期", "date")
        c_10 = _pick(df, "中国国债收益率10年", "中国国债收益率10年期", "y10")
        c_2 = _pick(df, "中国国债收益率2年", "中国国债收益率2年期", "y2")
        if c_d is None or c_10 is None:
            raise RuntimeError(f"国债列名变化：{list(df.columns)[:6]}")
        n = 0
        for _, r in df.iterrows():
            d = str(r[c_d]).strip()
            if not d or d == "nan":
                continue
            y10 = _to_float(r[c_10])
            y2 = _to_float(r[c_2]) if c_2 else None
            if y10 is not None:
                con.execute("INSERT OR REPLACE INTO bond_yield VALUES (?,?,?)", (d, y10, y2))
                n += 1
        con.commit()
        print(f"国债收益率缓存: {n} 个交易日（{df[c_d].iloc[-1]} 最新）")
    except Exception as e:
        print(f"国债收益率失败: {str(e)[:120]}")

    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
