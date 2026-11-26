# -*- coding: utf-8 -*-
"""部署自检：盘点本地 SQLite 数据库的行数（不修改任何数据）。"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def inspect(p: Path):
    if not p.exists():
        print(f"{p}  [缺失]")
        return
    size = p.stat().st_size
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except Exception as e:
        print(f"{p}  [无法打开] {e}")
        return
    try:
        tabs = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        parts = []
        for t in tabs[:8]:
            try:
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except Exception:
                n = "?"
            parts.append(f"{t}={n}")
        print(f"{p}  size={size}B  表: {', '.join(parts) if parts else '无'}")
    finally:
        con.close()


if __name__ == "__main__":
    targets = sys.argv[1:] or [
        "data/bars.db", "data/bars_incr.db", "data/cache/bars.db",
        "data/demo/bars.db", "data/demo/demo_bars.db", "data/demo/bars_incr.db",
    ]
    for t in targets:
        inspect(BASE / t)
