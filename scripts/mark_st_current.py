# -*- coding: utf-8 -*-
"""ST 标记（当前口径）：用股票名称里的 ST / *ST 回填**最新交易日**的 is_st。

背景：腾讯行情源没有 ST 字段，全字段入库时 is_st 全 0，`strategy_v3.filter_st` 形同虚设。
项目自带的 `data/fix_st_flags.py` 走 baostock 逐只重拉 isST，本机实测该接口已挂起（单只 5 分钟无返回），
因此先用"当前名称"口径兜底：

  仅写最新一个交易日的 is_st（ST/*ST 名称 → 1，其余 → 0），**不伪造历史**。
  历史 ST 口径需 baostock/Tushare 恢复后再用 fix_st_flags.py 回填，届时应重跑本脚本保持最新日一致。

用法：python scripts/mark_st_current.py
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BARS = BASE / "data" / "cache" / "bars.db"
BASIC = BASE / "data" / "cache" / "stock_basic.db"


def main() -> int:
    con = sqlite3.connect(str(BARS))
    latest = con.execute("SELECT MAX(date) FROM daily_bar WHERE adjust='qfq'").fetchone()[0]
    if not latest:
        print("bars.db 无数据")
        return 1

    b = sqlite3.connect(f"file:{BASIC}?mode=ro", uri=True)
    rows = b.execute(
        "SELECT code, name FROM stock_basic WHERE name LIKE '%ST%' OR name LIKE '%退%'").fetchall()
    b.close()
    st_codes = [c for c, _ in rows]
    if not st_codes:
        print("未从股票名称匹配到 ST 标的")
        return 1

    ph = ",".join("?" * len(st_codes))
    con.execute(f"UPDATE daily_bar SET is_st=0 WHERE date=? AND adjust='qfq'", (latest,))
    cur = con.execute(
        f"UPDATE daily_bar SET is_st=1 WHERE date=? AND adjust='qfq' AND code IN ({ph})",
        [latest, *st_codes])
    n = cur.rowcount
    con.commit()
    total = con.execute(
        "SELECT COUNT(*) FROM daily_bar WHERE date=? AND adjust='qfq' AND is_st=1", (latest,)).fetchone()[0]
    con.close()
    print(f"最新交易日 {latest}：标记 ST {n} 只（名称匹配 {len(st_codes)} 只，库内当日 ST 合计 {total} 只）")
    print("注意：仅当前日口径；历史 ST 未回填（见脚本说明）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
