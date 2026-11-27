# -*- coding: utf-8 -*-
"""修复 bars.db 中 preclose / pct_chg 为 NULL 的行（可重复执行）。

成因（2026-11-27 发现）：`scripts/pull_real_data.py` 增量拉取时按窗口切片，
窗口**第一行**没有前一日收盘 → `df["close"].shift(1)` 得到 NaN → 写库时
`INSERT OR REPLACE` 把原本正确的行覆盖成 NULL。
实测：2026-11-20 / 11-23 两天几乎全市场（各 5213/5216 行）pct_chg 为 NULL，
导致涨停次数、动量、振幅、反转等依赖 pct_chg 的因子在这两天全部失真
（例：岳阳兴长 000819 11-23 涨停，短线卡片却显示"近5日涨停 0 次"）。

修复：按 (code, adjust) 用**前一条已存在行的 close** 回填 preclose，再算 pct_chg。
用法：
    python scripts/fix_preclose_pctchg.py --dry-run    # 只统计
    python scripts/fix_preclose_pctchg.py              # 实修
"""
import argparse
import sqlite3
import sys
import time

DB = "data/cache/bars.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="只修前 N 行（调试）")
    args = ap.parse_args()

    con = sqlite3.connect(DB, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    n_null = con.execute(
        "SELECT COUNT(*) FROM daily_bar WHERE adjust='qfq' AND (preclose IS NULL OR pct_chg IS NULL)"
    ).fetchone()[0]
    print(f"待修复行数（preclose 或 pct_chg 为 NULL）: {n_null}")
    if args.dry_run or n_null == 0:
        con.close()
        return 0

    sql_rows = con.execute(
        "SELECT rowid, code, adjust, date, close FROM daily_bar "
        "WHERE adjust='qfq' AND (preclose IS NULL OR pct_chg IS NULL) "
        "ORDER BY code, date" + (f" LIMIT {args.limit}" if args.limit else "")
    ).fetchall()
    print(f"本次处理 {len(sql_rows)} 行")

    t0 = time.time()
    fixed = skipped = 0
    updates = []
    for rowid, code, adjust, date, close in sql_rows:
        prev = con.execute(
            "SELECT close FROM daily_bar WHERE code=? AND adjust=? AND date<? ORDER BY date DESC LIMIT 1",
            (code, adjust, date)).fetchone()
        if not prev or prev[0] is None or close is None:
            skipped += 1
            continue
        pc = prev[0]
        pct = (close / pc - 1.0) if pc else None
        updates.append((pc, pct, rowid))
        fixed += 1
        if len(updates) >= 2000:
            con.executemany("UPDATE daily_bar SET preclose=?, pct_chg=? WHERE rowid=?", updates)
            con.commit()
            updates = []
    if updates:
        con.executemany("UPDATE daily_bar SET preclose=?, pct_chg=? WHERE rowid=?", updates)
        con.commit()

    left = con.execute(
        "SELECT COUNT(*) FROM daily_bar WHERE adjust='qfq' AND (preclose IS NULL OR pct_chg IS NULL)"
    ).fetchone()[0]
    con.close()
    print(f"修复 {fixed} 行，跳过 {skipped} 行（无前收盘/无收盘，多为各股首日），耗时 {time.time()-t0:.1f}s")
    print(f"剩余未修复: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
