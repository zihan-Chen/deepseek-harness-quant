# -*- coding: utf-8 -*-
"""部署引导：把演示数据落到统一缓存目录 data/cache（演示模式）。

背景：仓库内既有模块按相对路径 `data/cache/xxx.db` 直读（rank_live、sector_research 等 60+ 处），
而 data/cache.py 走 LWQUANT_CACHE_DIR。两者必须指向同一目录，否则演示/真实数据读不到 → 接口 500。
本脚本只做"演示数据落位"，不生成任何真实行情：

    data/cache/bars.db         ← data/demo/demo_bars.db（30 只合成股票 × 250 交易日）
    data/cache/bars_incr.db    ← 空增量库（同 schema）
    data/cache/stock_basic.db  ← data/demo/demo_stock_basic.csv（code/name，行业留空）
    data/cache/_DEMO_DATA.md   ← 演示数据说明（避免误当真实行情）

真实数据接入时：清空 data/cache 后按 docs/数据说明.md 拉取，演示库与真实库不要混放。
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CACHE = BASE / "data" / "cache"
DEMO = BASE / "data" / "demo"

SCHEMA_BARS = """
CREATE TABLE IF NOT EXISTS daily_bar (
    code TEXT NOT NULL, date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    preclose REAL, volume REAL, amount REAL,
    turn REAL, pct_chg REAL, is_st INTEGER,
    adjust TEXT NOT NULL, source TEXT NOT NULL,
    PRIMARY KEY (code, date, adjust));
CREATE INDEX IF NOT EXISTS idx_daily_bar ON daily_bar (code, adjust, date);
CREATE TABLE IF NOT EXISTS bar_meta (
    code TEXT NOT NULL, adjust TEXT NOT NULL,
    start_date TEXT, end_date TEXT, rows INTEGER, updated_at TEXT,
    PRIMARY KEY (code, adjust));
"""

MARKER = """# 演示数据（合成，非真实行情）

> ⚠️ 本目录当前的 `bars.db` / `stock_basic.db` 由 `data/demo/build_demo_db.py` 生成，
> **全部为随机游走合成序列，不得用于任何策略结论或交易决策**。

- 生成：`python data/demo/build_demo_db.py` → `scripts/_stage_demo_cache.py`
- 内容：30 只合成股票 × 250 交易日（日线 OHLCV + turn），股票名 `演示股NN`，行业留空
- 切换真实数据：删除本目录下 `*.db`，按 `docs/数据说明.md` 用 Tushare/AKShare 拉取
- 落位时间：{ts}
"""


def copy_bars() -> str:
    src, dst = DEMO / "demo_bars.db", CACHE / "bars.db"
    if not src.exists():
        return "跳过（demo_bars.db 缺失，请先运行 data/demo/build_demo_db.py）"
    if dst.exists() and dst.stat().st_size >= src.stat().st_size and dst.stat().st_mtime >= src.stat().st_mtime:
        return "跳过（已是最新演示库）"
    shutil.copyfile(src, dst)
    return f"已落位 bars.db（{dst.stat().st_size / 1024:.0f} KB）"


def ensure_incr() -> str:
    p = CACHE / "bars_incr.db"
    con = sqlite3.connect(str(p))
    con.executescript(SCHEMA_BARS)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM daily_bar").fetchone()[0]
    con.close()
    return f"已就绪 bars_incr.db（{n} 行）"


def build_stock_basic() -> str:
    p = CACHE / "stock_basic.db"
    con = sqlite3.connect(str(p))
    con.execute("""CREATE TABLE IF NOT EXISTS stock_basic (
        code TEXT PRIMARY KEY, name TEXT, industry TEXT,
        ipo_date TEXT, out_date TEXT, status TEXT)""")
    n = 0
    csv = DEMO / "demo_stock_basic.csv"
    if csv.exists():
        for line in csv.read_text(encoding="utf-8").splitlines()[1:]:
            if not line.strip():
                continue
            code, _, name = line.partition(",")
            con.execute("INSERT OR REPLACE INTO stock_basic VALUES (?,?,?,?,?,?)",
                        (code.strip(), name.strip(), "", "", "", "L"))
            n += 1
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM stock_basic").fetchone()[0]
    con.close()
    return f"已就绪 stock_basic.db（写入 {n}，库内 {total}）"


def main() -> int:
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"缓存目录：{CACHE}")
    print(f"  {copy_bars()}")
    print(f"  {ensure_incr()}")
    print(f"  {build_stock_basic()}")
    (CACHE / "_DEMO_DATA.md").write_text(
        MARKER.format(ts=datetime.now().strftime("%Y-%m-%d %H:%M")), encoding="utf-8")
    print("  已写入 data/cache/_DEMO_DATA.md（演示数据声明）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
