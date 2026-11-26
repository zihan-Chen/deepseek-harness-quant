# -*- coding: utf-8 -*-
"""部署引导：从 .example 模板生成本地配置文件（幂等，已存在则跳过）。

规则：
  - config/params.yaml       ← params.yaml.example，并按顺序把 "<your-config>" 占位符
                               替换为合理的本地缺省值（不改动模板本身）
  - config/strategies.yaml   ← strategies.yaml.example
  - config/etf_pool.yaml     ← etf_pool.yaml.example
  - data/demo/bars.db        ← demo_bars.db（演示数据，bars.db 才是 cache.py 读取名）

不写入任何真实密钥；Tushare/JQData token 留空，由用户在 params.yaml 自行填写。
"""
import shutil
import sys
from pathlib import Path

import yaml

BASE = Path(__file__).resolve().parent.parent
CFG = BASE / "config"
DEMO = BASE / "data" / "demo"

# 与 params.yaml.example 中出现顺序严格一致的占位符替换值（共 20 个）
PLACEHOLDERS = [
    "data/cache",                       # data.cache_dir
    "相对仓库根；环境变量 LWQUANT_CACHE_DIR 优先",  # data.cache_dir_note
    "",                                 # data.tushare_token（未接入）
    "",                                 # data.tushare_api_url
    "",                                 # data.tushare_backup.url
    "",                                 # data.tushare_backup.api_key
    "",                                 # data.jqdata_user
    "",                                 # data.jqdata_password
    "大盘/质量池",                        # pead.scope
    "季度滚动 IC 校准",                   # weights.rebalance
    "v1.0.0",                           # layers.weight_version
    "2026-11-25",                       # layers.weight_date
    "指数遗忘",                           # layers.decay_mode
    "half_kelly+van_tharp",             # risk.position_model
    "2019-01-01",                       # backtest.start
    "2024-01-01",                       # backtest.out_of_sample_start
    "ew_regime",                        # strategy_v3.mode
    "等权+Regime；市值过滤已归零，无前视",   # strategy_v3.lookahead_note
    "缓存数据自 2019-01-01 起",           # data_audit.data_start_note
    "2020-01-01",                       # factor_pool.ts_eval_start
]
TOKEN = '"<your-config>"'


def build_params() -> str:
    src = (CFG / "params.yaml.example").read_text(encoding="utf-8")
    dst = CFG / "params.yaml"
    if dst.exists():
        return "跳过（已存在）"
    n = src.count(TOKEN)
    if n != len(PLACEHOLDERS):
        raise SystemExit(f"模板占位符数量不符：模板 {n} 个，脚本 {len(PLACEHOLDERS)} 个")
    for v in PLACEHOLDERS:
        src = src.replace(TOKEN, '"%s"' % v, 1)
    if TOKEN in src:
        raise SystemExit("仍有未替换的占位符")
    yaml.safe_load(src)                    # 语法校验：解析失败即中断，不落盘
    dst.write_text(src, encoding="utf-8")
    return f"已生成（{n} 个占位符已填本地缺省值）"


def copy_if_missing(name: str) -> str:
    src, dst = CFG / f"{name}.yaml.example", CFG / f"{name}.yaml"
    if dst.exists():
        return "跳过（已存在）"
    shutil.copyfile(src, dst)
    yaml.safe_load(dst.read_text(encoding="utf-8"))
    return "已生成"


def stage_demo_db() -> str:
    """cache.py 只认 bars.db；演示数据文件名为 demo_bars.db → 复制一份。"""
    src, dst = DEMO / "demo_bars.db", DEMO / "bars.db"
    if not src.exists():
        return "跳过（demo_bars.db 不存在，请先运行 data/demo/build_demo_db.py）"
    if dst.exists() and dst.stat().st_size == src.stat().st_size and dst.stat().st_mtime >= src.stat().st_mtime:
        return "跳过（已是演示库）"
    shutil.copyfile(src, dst)
    return "已同步 demo_bars.db → bars.db"


def main() -> int:
    print(f"仓库根：{BASE}")
    print(f"  params.yaml      : {build_params()}")
    print(f"  strategies.yaml  : {copy_if_missing('strategies')}")
    print(f"  etf_pool.yaml    : {copy_if_missing('etf_pool')}")
    print(f"  演示库 bars.db   : {stage_demo_db()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
