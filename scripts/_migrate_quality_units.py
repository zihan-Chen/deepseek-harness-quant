# -*- coding: utf-8 -*-
"""一次性迁移：把财报/质量库的比率字段从"百分数"改回项目约定的"小数"。

背景：`scripts/pull_finance_ths.py` 直接存了同花顺返回的百分数（如毛利率 89.58），
而项目消费端一律按小数处理：
  - `risk/stock_risk._check_row` 的脏数据闸门 `gp > 1.0 or liab > 1.5` → 全部判 NO_DATA
  - `factors/opportunities/stock_check` 显示 `roe*100` → 变成 2499%
  - `risk/beneish._tata_proxy` 以 `cfo_to_np >= 1.0` 判断现金覆盖净利 → 全部失真
  - `scan` 的 `gross_margin` 阈值同理

做法：按列中位数判断当前是百分数还是小数（百分数中位数 > 1.5），是则 ÷100；
      幂等，可重复执行。`current_ratio`（流动比率）本来就是倍数，不动。
用法：python scripts/_migrate_quality_units.py [--dry-run]
"""
import sqlite3
import sys

QD = "data/cache/finance_quality.db"
FIN = "data/cache/finance.db"
PCT_COLS = ["roe_avg", "gp_margin", "np_margin", "liability_to_asset", "cfo_to_np", "cfo_to_or"]


def convert(con, table, cols, dry=False):
    for col in cols:
        vals = [abs(v) for (v,) in con.execute(
            f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL")]
        if not vals:
            print(f"  {table}.{col}: 无数据，跳过")
            continue
        vals.sort()
        med = vals[len(vals) // 2]
        if med > 1.5:
            if not dry:
                con.execute(f"UPDATE {table} SET {col}={col}/100.0 WHERE {col} IS NOT NULL")
            print(f"  {table}.{col}: 中位数 {med:.2f} → ÷100 {'(dry)' if dry else '已改'}")
        else:
            print(f"  {table}.{col}: 中位数 {med:.3f} → 已是小数，跳过")


def main() -> int:
    dry = "--dry-run" in sys.argv
    con = sqlite3.connect(QD)
    print("质量库 finance_quality.db：")
    convert(con, "quality", [c for c in PCT_COLS if c != "cfo_to_or"] +
            (["cfo_to_or"] if any(r[0] for r in con.execute(
                "SELECT 1 FROM pragma_table_info('quality') WHERE name='cfo_to_or'")) else []), dry)
    if not dry:
        con.commit()
    con.close()

    con2 = sqlite3.connect(FIN)
    print("财报库 finance.db：")
    convert(con2, "finance_report", ["roe"], dry)
    if not dry:
        con2.commit()
    con2.close()
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
