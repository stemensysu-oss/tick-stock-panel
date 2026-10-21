# 基金与可转债研究扩展

## 基线与入口

- 上游：`shy3130/tick-stock-panel`，Tag `v0.3.11`。
- 基线 commit：`59e2772f51dfc6306e013f1d55b08ba3ce2f235f`。
- Fork 分支从 `648f096ee307fcb078150e0e76a04b9deff117bb` 建立；该提交与上述 v0.3.11 的文件树完全一致。
- 开发分支：`feature/funds-convertibles`。
- 许可证：继续遵循仓库根目录的 MIT LICENSE，保留原版权声明。
- 启动方式：沿用主项目 README 的源码或 Docker 构建流程；预编译的上游安装包不包含本分支的新代码。
- 菜单新增「基金研究」(`/funds`) 和「可转债研究」(`/convertibles`)。

实现采用 L2 扩展，后端注册独立路由，前端注册独立页面和导航。股票、策略、回测、监控和已有数据目录没有迁移。

## 基金研究

输入六位代码和明确后缀，例如 `000001.OF`、`510300.SH`、`159915.SZ`。`.OF` 表示场外基金，`.SH/.SZ` 是用户明确指定的场内代码。标的支持范围以数据源实际响应和权限为准。

### 已实现

- 基金名称、管理人、基金经理、成立日期及资料中的单位净值。
- 近一周至近五年的历史净值，分别查看单位净值和复权净值。
- 股票、债券、基金等已披露持仓及占净值比重、报告期、公告日。
- 配置缺失、权限不足、限流、数据缺失、格式异常分别显示明确状态。
- 三类数据独立请求；一类失败不掩盖其他类别的结果。

### 扶摇 Key 配置

服务端复用项目已有的扶摇密钥读取机制，新增页面不会读取、显示或保存密钥。

1. **同时具备 A 股及所需基金接口权限的 Key**：可在「设置 → 数据源」保存。现有保存流程会先验证 A 股快照接口。
2. **只有基金权限的 Key**：将 `FUYAO_API_KEY` 配置为启动后端进程的环境变量，然后重启后端。使用项目 `dev.sh`、`dev.ps1` 或当前 Docker Compose 配置时，也可写入项目根目录 `.env`；手工启动 uvicorn 时需显式传入 `--env-file`，Docker run 需加 `--env-file .env`。仅放置 `.env` 文件并不保证所有启动方式都加载该变量。在基金页点击「重新检查配置」。

已在设置页保存的 Key 优先于环境变量。如果需要从旧 Key 切换到环境变量，应先在设置页清除旧 Key。不要提交包含真实 Key 的 `.env` 或运行时数据文件。

「已配置」只表示读取到了配置，不代表资料、净值和持仓的全部访问权限均已验证。每类接口在实际查询时验证权限。首版没有使用真实有权限的 Key 做线上联调。

### 数据口径

- 净值沿用数据源币种，未做汇率换算；数据源未提供币种字段，界面不会默认标为人民币。
- 单位净值变化可能受到分红、份额折算影响，不能直接视为投资总回报。
- `adj_nav` 是复权净值，不是累计净值。
- 持仓比例为百分数：`0.12` 显示为 `0.12%`，不按数值大小猜测单位。
- 毫秒时间戳按北京时间转换；净值日、报告期、公告日与供应商快照时间分别处理。
- 披露持仓并非实时持仓；缺失值显示为未知，不补成零。
- 不输出未确认单位的基金规模，不提供盘中估值。

### 数据源边界

`FundDataProvider` 协议定义 `profile(ticker)`、`nav(ticker, range)`、`holdings(ticker)`，统一输出 `models.py` 中的响应模型。新供应商应实现该协议并完成单位、日期、空值和错误归一，不需要让前端理解供应商原始响应。

本扩展的基金数据集独立于原 A 股行情 provider；当前实现选择扶摇，未加入原股票能力路由矩阵。它复用已有 `FuyaoClient` 和密钥存储，不创建新的密钥数据库。

官方契约：

- [基金资料](https://fuyao.aicubes.cn/docs/api-reference/fund-profile/)：`/api/fund/profile/detail`
- [基金表现](https://fuyao.aicubes.cn/docs/api-reference/fund-performance/)：`/api/fund/performance/nav`
- [基金持仓](https://fuyao.aicubes.cn/docs/api-reference/fund-holdings/)：`/api/fund/portfolio/holdings`

## 可转债工作台

可转债扩展已从基础 CSV 研究升级为多视图工作台，支持 **28 个显示字段、组合筛选、自选与排除名单、最多四只对比、散点图、强赎/回售观察、下修和公告记录**。详情支持现金流试算、税前到期收益率、回售情景收益率、纯债折现及简化欧式转股期权模型。

清单内转债及明确正股的报价可通过已有 TickFlow Key 更新；条款、评级、剩余规模、持仓及公告仍需独立输入。配置 Key 只表示存在配置，不代表实际行情权限已验证。页面不会伪造缺失字段。

CSV 更新同代码时保留研究记录，移出清单的条目会移除；完整 JSON 备份和校验恢复包含现金流、条款和公告。读写保持原子替换和版本冲突保护，旧 schema 1 清单兼容读取。自选与显示偏好仅保存在当前浏览器。

字段字典、完整使用步骤、计算口径、数据时间、接口和升级边界见 **[可转债工作台说明](convertibles-workbench.md)**。本部署仍仅支持每张面值 100 元人民币的清单；筛选和模型不构成交易指令。没有自动抓取集思录或已验证的全市场条款数据库。

## HTTP 接口

新增接口沿用面板 `/api/` 全局认证，没有新增认证豁免，也没有新增外部 API Token 权限档或 MCP 工具。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/ext/funds/status` | 配置状态；不返回密钥 |
| `GET /api/ext/funds/{ticker}/profile` | 基金资料 |
| `GET /api/ext/funds/{ticker}/nav?range=year` | 历史净值 |
| `GET /api/ext/funds/{ticker}/holdings` | 披露持仓 |
| `GET /api/ext/convertibles` | 当前清单、研究资料及重算指标 |
| `GET /api/ext/convertibles/status` | 行情配置状态，不返回 Key |
| `POST /api/ext/convertibles/refresh` | 刷新已有清单的债券及正股报价 |
| `GET /api/ext/convertibles/template` | 空 CSV 模板 |
| `POST /api/ext/convertibles/preview` | `{csv_text, as_of}`，只校验 |
| `POST /api/ext/convertibles/import` | `{csv_text, as_of, expected_revision, confirmed:true}` |
| `POST /api/ext/convertibles/{code}/analyze` | `{research, expected_revision?}`，只读试算 |
| `PUT /api/ext/convertibles/{code}/research` | `{research, expected_revision}`，保存研究 |
| `POST /api/ext/convertibles/restore/preview` | `{snapshot}`，校验完整备份 |
| `POST /api/ext/convertibles/restore` | `{snapshot, expected_revision, confirmed:true}` |

基金错误：配置缺失 503、无效 Key 或权限不足 403、标的不存在 404、参数或不支持的类型 422、限流 429、网络或响应格式异常 502。供应商原始错误正文不会直接返回给前端。

## 开发与升级

新增代码主要位于：

- `backend/app/custom/funds/`
- `backend/app/custom/convertibles.py`
- `backend/app/services/convertibles_*.py`
- `frontend/src/custom/funds/`
- `frontend/src/custom/convertibles/`

核心接线只追加 `frontend/src/lib/api.ts` 的类型和请求，以及 `frontend/src/lib/queryKeys.ts` 的查询键。未来合并上游版本时重点复核这两份共享文件，并重跑扩展与数据源契约测试。不复制主页面、不覆盖主路由、不改变主数据源的默认路由。

功能回滚可以回退本分支的功能提交；导入数据单独存放，代码回退不应删除用户数据。

## 首版验证记录与后续验证

以下为基础版的验证记录；工作台新增测试命令见 [工作台说明](convertibles-workbench.md#验证)，本次最终结果见 [工作台交付记录](convertibles-workbench-delivery.md)。在安装仓库锁定依赖后执行：

```bash
# backend/
uv run --frozen pytest tests/test_custom_funds.py tests/test_custom_convertibles.py tests/test_extensions.py tests/test_fuyao_provider.py tests/test_fuyao_financial.py tests/test_openapi_contract.py -q
uv run --frozen ruff check app/custom/funds app/custom/convertibles.py app/services/convertibles_research.py tests/test_custom_funds.py tests/test_custom_convertibles.py

# frontend/
pnpm exec vitest run src/extensions/runtime.test.ts src/custom/funds src/custom/convertibles
pnpm build

# repository root
git diff --check
```

2026-10-21 基础版的历史验证：上述后端六个测试文件共 **167 项通过**；前端扩展注册及新增功能共 **18 项通过**；Ruff、TypeScript、Vite 构建和 `git diff --check` 通过。测试覆盖真实数值断言、单位日期归一、缺配置/无权限、无数据/异常响应、导入原子性、版本冲突与查询竞态。

独立临时数据目录中的完整应用 HTTP 联调也通过：缺 Key 返回 503；预览不写入；120/10/10 的价格得到 100/20/140；缺值保留；确认导入后可读取；旧版本确认返回 409；非 100 元面值被拒绝；两个前端地址均返回页面。测试记录没有进入用户数据或提交内容。

当前环境的 pnpm 外层会触发自动安装，受到运行环境限制；验证使用已安装的 `node_modules` 直接运行 Vitest、`tsc -b` 和 `vite build`，即 package script 的同一构建链。FastAPI TestClient 在隔离环境的线程事件循环中会挂起，使用可运行本地线程通信的执行环境后同一测试立即通过，未修改依赖或生产代码规避测试。

基础版验证时未使用真实扶摇 Key，也没有新的桌面安装包。工作台版本的后续浏览器检查与数据源联调限制以交付记录为准。
