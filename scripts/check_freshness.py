# -*- coding: utf-8 -*-
"""盘点各数据/产物的新鲜度（只读）。"""
import glob
import os
import sqlite3
import time


def mt(p):
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p)))
    except Exception:
        return "缺失"


def q(db, sql):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchone()[0]
    finally:
        con.close()


print("bars.db 最新交易日 :", q("data/cache/bars.db", "SELECT MAX(date) FROM daily_bar"), "| 文件", mt("data/cache/bars.db"))
print("finance 最新报告期 :", q("data/cache/finance.db", "SELECT MAX(period) FROM finance_report"), "| 文件", mt("data/cache/finance.db"))
print("hist_mv 最新月份   :", q("data/cache/hist_mv.db", "SELECT MAX(month) FROM hist_mv"), "| 文件", mt("data/cache/hist_mv.db"))

targets = [
    ("logs/opp_pool_*.json", "机会池 opp_pool"),
    ("logs/tech_pitch_*.json", "短线 tech_pitch"),
    ("report/daily_report_*.md", "日报"),
    ("output/global_rotation.json", "五福轮动"),
    ("output/etf_map.json", "ETF 映射"),
    ("output/timing_system.json", "择时系统"),
    ("logs/rank_live_*.json", "实盘排名"),
    ("output/daily_signal.json", "今日信号"),
]
for pat, label in targets:
    fs = sorted(glob.glob(pat), key=os.path.getmtime)
    if fs:
        print(f"{label:<16}: {mt(fs[-1])}  ({os.path.basename(fs[-1])})")
    else:
        print(f"{label:<16}: 缺失")
