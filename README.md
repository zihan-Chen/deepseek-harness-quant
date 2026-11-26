# DeepSeek HARNESS Quant

自然语言驱动的 A 股量化系统。低频。主观决策 + 写死引擎 + 数据裁决。

AI 不预测个股。这是硬约束，不是选项。

```
驱动层  语言模型        控制 · 挖因子 · 审计 · 牛散蒸馏
执行层  写死引擎        评分 · 回测 · 风控 · 扫描（确定性 Python，可复现）
事实层  数据系统        PIT · T+1 · 覆盖率分年核查（可证伪）
```

## 本 fork 的改动（2026-11-25 ~ 11-26 · 源码部署 + 真实数据接入）

> 本仓库 fork 自 [yuanwang589-dev/deepseek-harness-quant](https://github.com/yuanwang589-dev/deepseek-harness-quant)，
> 在 Windows 上完成了一次完整源码部署、真实 A 股数据接入与若干线上故障修复。
> 完整过程记录见 [docs/本地部署记录.md](docs/本地部署记录.md)。

### 1. 部署环境

| 项 | 做法 |
|---|---|
| Python | 仓库内独立 `.venv`（Python 3.14.10），**不走 conda、也不用 PATH 上的嵌入式 Python**（后者无 pip/依赖） |
| Node | 官方便携版 **v24.22.3** 解压到 `runtime/node/`（`launcher.py` 优先使用它），HARNESS 运行时 `dsh 0.1.0-rc.6` |
| 依赖 | `requirements.txt` 补 **`pyarrow`** —— 原清单漏了它，凡读 parquet 的模块（五福轮动/分钟数据/subj_quant）都会报 `Unable to find a usable frame engine` |
| 启停 | `启动.cmd` 改为 `.venv` 优先；新增 `停止.cmd` + `scripts/stop_services.ps1`（按端口 8787/3080 停止） |

### 2. 真实数据接入（全部免费源，无需 Tushare token）

| 数据 | 脚本 | 结果 |
|---|---|---|
| 全市场日线（前复权） | `scripts/pull_real_data.py`（腾讯源，6 并发） | **5224 只 × 1915 日 = 8,603,715 行**，12.2 分钟，0 失败 |
| 股票列表 + 行业 | `data/fetch_stock_basic.py`（baostock） | 5566 只（5224 只含行业） |
| 沪深300（择时基准） | `scripts/load_index.py` | 1915 行（写入 `bars.db` 的 `SH.000300`） |
| 历史流通市值 | `data/build_hist_mv.py`（amount÷turn 反推） | 83 个月 / 386,772 行 |
| 财报（PIT） | `scripts/pull_finance_ths.py`（同花顺，宽表→长表适配） | `finance.db` 153,837 行 + `finance_quality.db` 153,589 行，5224 只全覆盖 |
| 当前 ST 标记 | `scripts/mark_st_current.py` | 最新交易日 189 只（历史 ST 待数据源恢复后回填） |

> 为什么不用项目自带的 `data/bulk_loader.py`：实测本机 baostock 单只 3–11 秒（全量需 8–10 小时），
> 东财 `push2` 接口对本机 IP 限流，新浪 `stock_zh_a_hist_sina` 忽略 `adjust`（无复权）。腾讯源 0.55 秒/只且支持 qfq。

### 3. 修复的线上故障

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 8787 端口被旧实例占用；启动后部分接口 500 | `launcher.py` 强行把缓存目录改写成 `data/`，与 `data/cache.py` 及 60+ 处写死的 `data/cache/*.db` 冲突 | `launcher.py` 改为 `环境变量 > params.yaml > data/cache` |
| 2 | HARNESS 启动即退，无任何日志 | 子进程输出丢进 `DEVNULL` | 落盘 `logs/harness.log` |
| 3 | 控制台"暂不可达" | 前端调 `/api/proxy/quantapi/*`，开源版桥接插件注册的是 `/quant/*` | `deck_server.py` 反代增加 `_proxy_path()` 命名空间映射 |
| 4 | 控制页"读取失败：Error: HTTP 404" | `/api/harness` 快照文件缺失时返回 404 | 改为返回 200 + 现场探活快照（在线状态/版本/模型），文件存在时仍读文件 |
| 5 | 门户"离线 2 个" | `/api/tech_pitch`、`/api/daily_report` 缺产物时返回 404，健康探测只认 200 | 改为 200 空态（`ok:false, empty:true`）；并补跑 `tech_pitch_v3.py`、`daily_report_auto.py` 产出真实数据 |
| 6 | 全市场扫描报"行情面板为空" | 9 处 `Path(p).as_uri()` 对相对路径抛 `ValueError`，外层 `except: continue` 静默跳过 | 统一改为 `.resolve().as_uri()`（扫描/实时/持仓/短线钩子等） |
| 7 | 扫描跑 21 分钟后 `UnicodeEncodeError: 'gbk' can't encode '⚡'` | Windows 控制台 GBK，脚本 print emoji | `scan.py`、`daily_report_auto.py` 顶部固定 stdout 为 UTF-8 + `errors=replace` |
| 8 | 日报生成 `FileNotFoundError: report\...` | 全新仓库没有 `report/` 目录 | `daily_report_auto.py` 写入前自动建目录 |
| 9 | 五福轮动报 `Unable to find a usable engine` | 缺 pyarrow，且 `data/factorpool/output/cache/wufu_*.parquet` 是作者侧产物、仓库不含 | 装 pyarrow；新增 `scripts/build_wufu_cache.py` 用新浪免费接口重建 4 指数 + 9 ETF 缓存；`widget()` 资产名改按列名映射（原来按位置硬编码） |
| 10 | `/api/etf_map` 404、ETF 页空白 | 该路由是静态文件路由，`output/etf_map.json` 从未生成 | 跑 `etf/etf_map.py`（52 秒）→ 41 张 ETF pitch 卡 + 8 只配置建议 |
| 11 | 门户"实时行情暂不可用" | akshare 1.20.46 把 `stock_zh_a_spot` 改名 `stock_zh_a_spot_sina` | `live_api.py` 动态解析新旧函数名；`market_open` 改按 A 股交易时段判断（原来恒为 True） |
| 12 | 短线卡片"换手 12.7%"与同花顺当日 11.50% 对不上 | `tech_pitch_v3` 把载入的 **10 天**换手均值当"近5日换手"显示 | 情绪窗口严格取 5 日；文案改为 `换手 今日X% / 5日均Y%` |
| 13 | ETF 映射每天必挂（首跑 44 只全失败） | 缓存 CSV 的 date 是字符串、新浪返回 datetime.date，比较时类型冲突 | 统一转 `YYYY-MM-DD` 再比较；无可用 ETF 时给出明确中断原因 |
| 14 | 短线池推荐的股票，搜索诊断却是「E 回避」（如皇冠新材） | ① 诊断把"缺数据"当"差"（新股上市仅 18 日 → 技术/估值 0 分）；② 质量库 code 带后缀匹配 6 位表 → 全市场风控 NO_DATA；③ 财报脚本存了百分数而项目约定小数 | 诊断分级重做（新股/缺数据 → `NA`，低分无负面证据 → 「无机会」）；质量库按 6 位匹配；单位幂等迁移 ÷100；结论附带短线池交叉说明 |

### 4. 新增的运维脚本

| 脚本 | 用途 |
|---|---|
| `scripts/_bootstrap_config.py` | 从 `.example` 生成 `config/*.yaml`（params 里 20 个 `<your-config>` 占位符填本地缺省值） |
| `scripts/_stage_demo_cache.py` | 无真实数据时把演示库落到 `data/cache`（含 `_DEMO_DATA.md` 声明） |
| `scripts/_smoke_deploy.py` | 部署回归自检：从 `deck_server.py` **动态提取路由**并逐个探活（本次 121 条路由 / 36 个 API 全通过） |
| `scripts/_inspect_db.py` | 只读盘点各 SQLite 表行数（排查数据缺口） |
| `scripts/pull_real_data.py` / `load_index.py` / `pull_finance_ths.py` / `mark_st_current.py` / `build_wufu_cache.py` | 见上表 |

### 5. 当前验证状态

```
页面/API 回归      OK 121 / FAIL 0（.venv\Scripts\python.exe scripts\_smoke_deploy.py）
API 接口状态       36/36 在线
全市场扫描         1196 条机会（revalue 586 / event 593 …），Pitch 1 只（000089.SZ 深圳机场 97.1）
ETF 映射           41 张 pitch 卡 + 8 只配置建议（复制组合相关 0.759）
五福轮动           9 只全球资产动量面板（parquet 缓存已重建）
```

> **数据不随仓库分发**：`data/`、`logs/`、`output/`、`report/`、`config/params.yaml`、`harness/home/.credentials.yaml`
> 均已在 `.gitignore` 中；仓库只含代码、获取脚本与演示数据（合成序列），行情请按 `docs/数据说明.md` 自行获取。

### 6. 日更链路（2026-11-26 新增）

`scripts/daily_run.py` 把盘后需要的 16 步串成一条命令（约 **28–30 分钟**，其中全市场扫描约 22 分钟）：

```
增量日线(3.6min) → 沪深300 → 宏观缓存(社融/国债) → 五福 parquet
→ 机会扫描 --pitch → Pitch v2 → 短线科技池 → 三层池 → 择时系统
→ 远期池 T+1 → 止损监测 → 日报(--dry-run) → 五福轮动信号 → ETF 映射
→ 文件归档 → 部署自检(121 路由)
```

- 数据增量：`scripts/pull_real_data.py --incremental`，以库内最新交易日为基准回看 N 天，实测 **25.9 只/秒**（全市场约 3.6 分钟；全量 12 分钟只在首次/补历史时需要）
- 产物：`logs/daily_run_<ts>.log` + `logs/daily_run_<ts>_summary.json`（每步状态/耗时/失败清单）
- 计划任务：`DSHQuant-Daily`，每天 18:30 调 `scripts/daily.cmd`（隐藏控制台）
  停用 `schtasks /Change /TN "DSHQuant-Daily" /DISABLE`，删除 `schtasks /Delete /TN "DSHQuant-Daily" /F`
- 跳过参数：`--skip-fetch / --skip-scan / --skip-etf / --skip-verify`

### 7. 已知限制

- 估值类数据（PE/PB，走 tushare 备用服务器）未配置 → `value`/`quality_gap`/`pv_consensus` 类型扫描触发不了；
- 历史 ST 标记未回填（仅最新交易日）；
- 龙虎榜/股东户数/机构调研未拉取，相关因子为空；
- 择时的"政策"维度缺 EPU 数据（FRED 不可达，akshare 备源只到 2023-11）→ 固定中性 50，界面标注 `EPU缺失`；
- 择时的"宏观"维度依赖 `report/daily_signal.py`，该文件未包含在开源发布包中 → 目前回退 50。

---

## 开始

新用户直接走 [一键部署](docs/一键部署.md)。接入 AI API 后，数据源、配置、验证全交给 AI 向导，不必读本页其余内容。

## 接入 DeepSeek API

接入 API 后，语言模型接管驱动层。控制、挖因子、审计、魔改，全部解锁。不接入，则只有写死引擎，没有 AI。

**前提**：完整包（zip）已内置 HARNESS 运行时；单文件（exe）不含 HARNESS，AI 控制台不可用。系统需 Node.js 18+（https://nodejs.org），无则 HARNESS 自动跳过、量化系统照常。

**最快方式**：双击 `接入API.cmd`，粘贴 Key，自动写入并验证。

```bash
# 1. 获取 Key
#    https://platform.deepseek.com/api_keys

# 2. 复制凭据模板，填入 Key（或直接用接入API.cmd）
copy harness\home\.credentials.yaml.example harness\home\.credentials.yaml
#    编辑 .credentials.yaml：
#    DEEPSEEK_API_KEY: sk-<your-key>

# 3. 启动（打印「启动 DeepSeek HARNESS」即集成成功）
python launcher.py
#    http://127.0.0.1:8787/control
```

接入后，直接对话：

- **控制系统**：发「1」触发自主推进（审计 / 修复 / 归档，系统自我进化）
- **挖因子**：说「研究散户情绪量化」——AI 拆假设 → 生成因子 → 九步验证 → 入池或证伪
- **审计**：让 AI 自查前视、覆盖率、共线性、过拟合
- **牛散**：7 位牛散人格对话选股，决策自动入远期池验证
- **魔改**：动态 Cordis 插件热更新，系统行为运行时改，不重编译

其余数据源（Tushare 等）接入后让 AI 指导完成。核心逻辑：先接 AI 的 API，AI 帮你接剩下的。

## 架构

| 模块 | 职责 |
|---|---|
| data/ | 数据获取 + 本地缓存 + Point-in-Time（cache.py 唯一读取接口） |
| factors/ | 因子引擎 + 机会扫描 + 远期池（五池 T+1/5/20/60 验证） |
| strategy/ | 决策链（L0 择时 → L2 Pitch 审批 → T+1 执行）+ 组合构建 |
| risk/ | 风控七道（数据审计 / 因子健康 / FRC 排雷 / Beneish / 竞价 / 单因子 / L0 门控） |
| backtest/ | 回测引擎（T+1 开盘 / 一字板过滤 / 成本模型 / 结论分级） |
| etf/ | ETF 映射（策略暴露 → 可交易配置） |
| deck/ ui_v2/ | Web 决策台（9 页，前端零硬编码） |
| harness/ | DeepSeek HARNESS 运行时（AI 控制台 / 牛散桥 / 动态插件） |
| config/ | 策略注册表 / ETF 池 / 阈值，全部配置化 + .example 模板 |

## 因子

123+ 因子，全部 A 股本地实证（PIT / T+1 / 分年度）。九步入池，17+ 项证伪留档。

| 维度 | 代表 | 实证 |
|---|---|---|
| 换手率 | turn_mid_prox / turnover / turn_std20 | turn_mid_prox ICIR 0.87 |
| 低波动 | lowvol / std20 / downside_vol | 防守底仓主力 |
| 反转 | reversal20 / o2c 日内反转族 | limup_ex_5 ICIR 1.24 |
| 流动性 | amihud | 0.43，多空夏普 1.12 |
| 彩票/偏度 | max_ret20 / skew20 / rmax | max_ret20 0.64 |
| 振幅/动量 | amp20 / open_prem_20 | open_prem_20 0.96 |
| 基本面低频 | f_score / sue / accruals / asset_growth / bp | f_score 120日 0.49 |
| 短线涨跌停 | limit_up_* / consec_limit_down | 跌停排雷 0.97 |
| 机构行为 | lhb_jg_cnt_20 / shebao_chg | lhb 0.90 |
| 行业层 | ind_crowd_60 / ind_rs_20 | 拥挤 0.30 |
| Alpha101 | alpha015 / alpha050 / alpha006 / alpha003 / alpha044 | alpha015 0.76 |

来源：学术复现 · 开源策略库复刻 · 事件驱动实证 · 牛散蒸馏 · AI 自动挖掘 · 机构资金行为。

## Skill

12 个技能文件，封装方法论 + 资产 + 踩坑记录，AI 按需加载。

- 因子挖掘：factor-mining-workflow · alpha-gpt-factor-mining · alpha-gpt-researcher · backtest-acceptance
- 牛散蒸馏：niu-san-distillation + 林园 / 陈小群 / 章盟主 / 赵老哥 / 炒股养家 / 冯柳
- 系统维护：github-maintainer

## 安装与运行

```bash
# 源码
pip install -r requirements.txt
python data/demo/build_demo_db.py    # 生成演示数据
python launcher.py                   # deck:8787 + HARNESS:3080

# 单文件
QuantDeck.exe                        # 双击即用，自动开浏览器

# 完整包
DSHQuant-v1.0.9-Release.zip          # 解压即用，含 HARNESS 运行时
```

> **下载注意**：从 Release 页 **Assets 区**下载 `DSHQuant-v1.0.9-Release.zip`（完整包，含 HARNESS 运行时）。
> **不要**下载页面底部的 "Source code (zip)" —— 那是源码包，harness/node_modules 被排除，没有 AI 控制台。
> 判断：解压后 `harness\node_modules` 文件夹存在 = 完整包；不存在 = 下错了。

运行要求：Python 3.10+（源码）/ 无（exe）。HARNESS 控制台需 Node.js 18+（可选）。

## 数据

数据由用户自行获取。系统不分发数据。

- 行情来自第三方（Tushare 等）。仓库只含获取脚本 + 合成演示数据。
- 换手率 2019 年前缺失，2019 前换手类结论作废。
- 配置：`config/params.yaml.example`（Tushare token）。

## 许可

MIT。仅供研究学习。不构成投资建议。

## 文档

[资产盘点](docs/资产盘点.md) · [架构说明](docs/架构.md) · [一键部署](docs/一键部署.md) · [快速开始](docs/快速开始.md) · [HARNESS 接入](docs/HARNESS接入.md) · [数据说明](docs/数据说明.md) · [分钟数据接入](docs/分钟数据接入说明.md)

更新机制：`scripts/update.py`（manifest 驱动，用户配置保护，应用前自动备份）。
