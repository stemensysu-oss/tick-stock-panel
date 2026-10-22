# 多资产功能与数据源矩阵

调研日期：2026-10-22。本文依据用户截图的分类及下列供应商/交易所公开文档制定接入计划。**公开文档已阅读不等于真实 API 已调用成功；本轮新增模块没有任何已核验实时数据接入。** 权限、配额和字段可能变化，实际适配时须重新核验。既有基金/转债能力保留，不据历史测试记录推定当前账号可用。

## 1. 分类与功能矩阵

“导入”均指用户自行获取并有权使用的数据；“候选”均未接入本工作台。第一阶段 12 个分类的实时状态为不可用。

| 用户分类 / 模块 ID | 第一阶段 | 后续所需输入与功能 | 候选一手披露 / 文档化接口 | 延迟、权限与关键限制 |
| --- | --- | --- | --- | --- |
| 套利股 / `arbitrage` | 按事件类型导入，现金对价空间、日期、来源 | 现金选择权、换股价/比例、接受条件、截止日；按中概/港股私有化、供股权、A 股事件细分 | [港交所披露易](https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh)、[SEC EDGAR](https://www.sec.gov/search-filings)、发行人原文；A 股交易所公告 | 公告是事件驱动，不是报价；未确认通用免费结构化事件 API。投票、撤回、司法/监管条件、ADR 换股比及交割均需核验，现金价差不能替代换股/供股权估值 |
| 封闭基金 / `closed_end` | 导入价格、净值、到期日，同日同币种折溢价 | 封闭期、开放窗口、到期转型、分红、份额、可变现约束 | [Tushare fund_basic](https://tushare.pro/document/2?doc_id=19)、[fund_nav](https://tushare.pro/document/2?doc_id=119)，管理人合同/公告 | 目录/净值不是盘中报价；不同产品的到期日和开放安排不同，不能用名义到期日承诺回款 |
| ETF / `etf` | 价格/NAV 比较、来源日期 | 基础目录、市场价、IOPV、PCF、现金替代、申赎单位、成交与费率 | [Tushare etf_basic](https://tushare.pro/document/2?doc_id=385)、[fund_daily](https://tushare.pro/document/2?doc_id=127)，[TickFlow quotes](https://docs.tickflow.org/zh-hans/api-reference/实时行情/查询实时行情)，管理人 PCF | 文档化日线与付费盘中行情分开；NAV 不能充当 IOPV；PCF 及申赎资格缺失时不展示“可执行套利” |
| 现金管理 / `cash` | 分列记录百分比利率、每万份收益、口径和期限 | 货币基金收益、交易型货基、逆回购、资金可用/可取日、实际计息天数和费用 | 管理人收益公告；[中国货币网](https://www.chinamoney.com.cn/chinese/bkccpr/index.html?tab=2)的利率栏目；交易所逆回购信息 | 七日年化、单日万份收益、报价年利率和最终持有收益不同；利率页面不是面向个人可交易产品报价，不能简单跨品种排序 |
| REITs / `reits` | 价格、期间分派额与所填期间分派率 | 资产类型、经营数据、可供分配金额、权益登记/除息/派息日、扩募 | [上交所基金公告](https://www.sse.com.cn/disclosure/fund/announcement/)、管理人定期报告/分派公告 | 报告/分派依披露发布，不是日更 NAV；每 10 份分派须显式换算每份；不能把物业估值或预测分配当作可赎回净值 |
| LOF / `lof` | 价格/NAV、申购状态文本 | 场内/场外份额映射、申赎限额、转托管、到账日、最低费用 | [fund_basic](https://tushare.pro/document/2?doc_id=19)、[fund_nav](https://tushare.pro/document/2?doc_id=119)，管理人限购/暂停公告 | 截至调研日 fund_daily 官方页标题/描述为 ETF；不依第三方经验承诺全部 LOF 行情覆盖。折价不代表可即时赎回 |
| A/H 比价 / `ah` | 人工配对，同日 A/H/汇率比较 | 两市场实时报价、汇率来源/时间、交易日和停牌、同一发行人/股种证明 | [Tushare stk_ah_comparison](https://tushare.pro/document/2?doc_id=399)；[中国货币网人民币中间价](https://www.chinamoney.com.cn/chinese/bkccpr/index.html?tab=2)；授权港股报价 | Tushare 文档称盘后 17:00 更新，5000 积分起、历史从 2025-08-12 累积；其输出无独立汇率时间。中间价不是可成交外汇价；A/H 不假定可互换 |
| T+0 QDII / `qdii` | 日期透明的价格/NAV 比较、限购文本 | 当日回转资格、海外交易日、汇率、估值时差、申赎/转托管周期 | [etf_basic](https://tushare.pro/document/2?doc_id=385)、[fund_nav](https://tushare.pro/document/2?doc_id=119)，管理人公告；[上交所 ETF 问答](https://etf.sse.com.cn/fund/quertion/) | 类别名不证明具体证券 T+0 资格。二级市场当日回转与申购份额可卖/赎回到账是不同规则；滞后 NAV 的跨日溢价本阶段不计算 |
| 股息率/分红 / `dividends` | 明确期间现金分红、所填期间股息率 | 实施状态、期间、税前/税后、每股/每 10 股、送转、登记/除息/派息日 | [Tushare dividend](https://tushare.pro/document/2?doc_id=103)，发行人实施公告 | 文档称每日 20–21 点更新、至少 2000 积分；cash_div 为税后每股、cash_div_tax 为税前每股，不可按英文后缀猜。预案不得算作已兑现收益 |
| 新股 / `ipo` | 发行价、事件日、申购状态清单 | 申购代码、发行/上市日、额度、缴款/中签、发行量、规则变更 | [Tushare new_share](https://tushare.pro/document/2?doc_id=123)，交易所发行/上市公告 | 文档至少 120 积分；ipo_date=上网发行日、issue_date=上市日，名称易误解。发行量/申购上限为万股；本阶段不自动申购 |
| 债券 / `bonds` | 价格、到期日、导入收益率及口径 | 票息/付息日、赎回/回售、净价/全价/应计利息、面值/手数、评级、完整现金流 | 发行人募集文件、交易所债券公告/授权行情；后续可评估中国货币网估值 | 估值收益率、买卖报价收益率和现金流 IRR 不能混用；没有条款与现金流时不据到期日推算 YTM |
| 指数涨幅 / `indices` | 导入点位、涨跌幅、PE/PB | 指数目录、收益口径、成分/权重生效日、估值覆盖、窗口收益 | [Tushare index_basic](https://tushare.pro/document/2?doc_id=94)、[index_daily](https://tushare.pro/document/2?doc_id=95)，指数编制机构 | 文档 2000 积分起；点位不是币种价格；指数成分成交量和整市场成交量不同。保留核心四大指数的现有产品契约，不改成未经验证的全指数实时服务 |
| 可转债（原模块） | 复用 `/convertibles`，原研究/CSV/报价适配器 | 完整覆盖仍需条款、公告、配对和授权报价分别确认 | 原 [TickFlow quotes](https://docs.tickflow.org/zh-hans/api-reference/实时行情/查询实时行情) 适配器及用户研究资料 | 原实现可刷新清单报价；本轮不声称验证过用户 Key，也没有自动条款或公告库 |
| 基金研究（原模块） | 复用 `/funds`，fuyao 资料/NAV/披露持仓接口 | 依已配置源继续核验权限和各基金覆盖 | 当前代码 `backend/app/custom/funds/provider.py`；可另评估 [fund_portfolio](https://tushare.pro/document/2?doc_id=121) | 原 `FundStatus.permission_status` 明确为 unverified；报告期和公告日不同，披露持仓不是基金实时持仓 |
| 持仓（个人组合，后续） | 尚未新增个人组合模块 | 券商主动导入、账户/成交/现金、成本与税费、币种转换、分红及公司行动 | 用户授权导出的券商报表；不读取截图里的账户数据 | 个人持仓是私有账户资料，与公开基金持仓不是同一数据集；没有账户来源时不得虚构余额或同步状态 |

## 2. 已阅读的接口契约与接入门槛

以下均为文档事实；本版本没有为这些新模块发起有认证的联网行情核验。

| 来源 | 调研时文档说明 | 适配时必须验证 |
| --- | --- | --- |
| [TickFlow quotes](https://docs.tickflow.org/zh-hans/api-reference/实时行情/查询实时行情) / [FAQ](https://docs.tickflow.org/zh-Hans/faq) | 需要 API Key；按 symbols 或 universes 批量请求，文档举例 CN_ETF；免费服务日线盘后更新，与付费实时服务不同 | 各证券类别实际覆盖、权限、币种、时间戳、单位、停牌/休市、部分缺值；不能从支持市场后缀推定支持全部基金/事件字段 |
| [fund_basic](https://tushare.pro/document/2?doc_id=19) | 场内/场外目录，至少 2000 积分；含存续状态和日期 | 名称不能代替产品类型；代码和份额类别映射；封闭期与到期是否最新 |
| [fund_nav](https://tushare.pro/document/2?doc_id=119) | 至少 2000 积分；分别给出 ann_date、nav_date、unit_nav、accum_nav、adj_nav | 公告日与净值日、币种、缺值/修订；累计净值和复权净值不可替代单位净值算折溢价 |
| [etf_basic](https://tushare.pro/document/2?doc_id=385) / [fund_daily](https://tushare.pro/document/2?doc_id=127) | 两接口调研时均至少 5000 积分；前者含境内/QDII通道、跟踪指数；后者为收盘数据 | 日线的 pct_chg 为百分数、vol 为手、amount 为千元；本项目标准金额使用元时明确乘 1000；不得按旧博客的门槛承诺可用 |
| [fund_portfolio](https://tushare.pro/document/2?doc_id=121) | 季度更新，ann_date 与 end_date 分列；文档列 5000/8000 积分档的请求频次 | 报告覆盖的资产类型和完整性、公告时间、防未来函数；mkv 为元、amount 为股；不作为用户个人持仓 |

不在代码里存放以上供应商的 Key，不以此文档中列出的积分/套餐作为授权结果。来源接入应把“文档支持”“已配置”“请求成功”“字段及覆盖通过核验”“当前快照新鲜度”分别记录，不能用一个绿色连接图标替代它们。

## 3. 为什么第一阶段采用严格导入

当前需要同时处理行情、NAV、汇率、条款、公告和交易规则。它们来自不同发布方，更新频率和授权也不同。一个网页有表格不代表存在可持续、可合法复用的 API；一个证券有价格不代表其套利所需的所有条件已齐全。

第一阶段把可追溯输入、计算条件和来源状态先做成共用契约。使用者可以立即整理合法获得的资料，看到缺少哪些字段，而无需等待全量数据订阅。演示只用于了解交互，不作为无数据时的隐式回退。下一阶段可以按矩阵逐个替换输入来源，不改动研究页面的金融口径。

交易所说明也区分二级市场交易与一级市场申赎：[上交所 ETF 问答](https://etf.sse.com.cn/fund/quertion/)分别列出了回转交易品种、申赎对价和管理人公布 PCF 的流程。因此第一阶段的折溢价、对价空间与分派率是研究比较指标，没有自动交易、收益保证或即时套利含义。
