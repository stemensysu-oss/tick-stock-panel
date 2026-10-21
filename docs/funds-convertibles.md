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

## 可转债研究

本版支持 **每张面值 100 元人民币的可转债**。数据来源为用户导入 CSV，价格均为未复权的元单位。页面明确标记导入来源和数据日期，不声称实时行情。

### 导入步骤

1. 从页面下载空 CSV 模板，用 UTF-8 编码、逗号分隔保存数据。
2. 选择这批价格对应的数据日期，再上传文件或粘贴文本。同一批应采用一致的观察日期。
3. 点击预览，检查识别字段、计算结果、警告和具体行错误。
4. 确认后 **全量替换该研究清单**。需要保留的旧记录应包含在新 CSV 中；请自行保留原始 CSV 备份。

预览不写入。修改文本或日期后必须重新预览。任何一行失败、重复代码、非法数值或日期都会阻止整批保存。预览后如清单已被另一操作修改，返回 409，要求重新预览。

最大 2 MiB、2,000 条。支持 UTF-8 BOM 和中文常见表头。代码必须按文本保留六位数字，可带 `.SH/.SZ/.BJ`；不根据代码推断资产类型。

| 英文字段 | 中文表头示例 | 说明 |
| --- | --- | --- |
| `code` | 转债代码、债券代码 | 必填，六位代码，保留前导零 |
| `name` | 转债名称、债券名称 | 必填 |
| `bond_price` | 转债价格、现价 | 每张转债价格，元 |
| `stock_code` | 正股代码 | 可选 |
| `stock_name` | 正股名称 | 可选 |
| `stock_price` | 正股价格、正股价 | 未复权正股价格，元 |
| `conversion_price` | 转股价、转股价格 | 当前有效转股价，元 |
| `face_value` | 面值 | 只接受 100；留空时预览明确提示按 100 元 |
| `maturity_date` | 到期日期、到期日 | `YYYY-MM-DD` |
| `redemption_status` | 强赎状态、赎回状态 | 仅保存用户提供文字，缺失为未知 |

未知价格请留空。零或负价格、`NaN`、无穷值不能作为有效计算输入。未识别字段会提示并忽略，派生指标始终由后端重算；导入其他工具导出的 CSV 前，应核对原始价格列名。

### 指标计算

```text
转股价值 = 100 × 正股价格 ÷ 转股价
转股溢价率（%） = (转债价格 ÷ 转股价值 − 1) × 100
双低值 = 转债价格 + 转股溢价率的百分数值
```

例如，价格 120、正股价格 10、转股价 10，得到转股价值 100、溢价率 20%、双低值 140。双低是筛选约定，不是收益率。中间步骤不提前四舍五入，输出保留六位小数。缺少必要输入时指标为 `null`，筛选及排序不会将其视为零。

支持搜索代码或名称、价格/溢价率/双低上限筛选，以及价格、溢价率、双低、到期日排序；未知值始终排后，每页 50 条。

当前不提供自动报价、强赎触发判断、回售/下修条款、到期收益率或交易。强赎状态文字不能替代公告核对。

### 存储和并发

数据保存到现有 `data_dir` 下的 `custom/convertibles/snapshot.json`。服务端不保留平行内存缓存，每次读取持久快照，写入复用原子替换机制。确认导入前使用版本号校验，前端先取消旧查询再更新新快照，避免迟到响应覆盖页面。

损坏文件、未知 schema、权限或磁盘错误会明确报错并拒绝覆盖。本版采用项目既有的单后端进程模式；没有实现多个独立服务进程同时写同一数据目录的跨进程锁。

## HTTP 接口

新增接口沿用面板 `/api/` 全局认证，没有新增认证豁免，也没有新增外部 API Token 权限档或 MCP 工具。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/ext/funds/status` | 配置状态；不返回密钥 |
| `GET /api/ext/funds/{ticker}/profile` | 基金资料 |
| `GET /api/ext/funds/{ticker}/nav?range=year` | 历史净值 |
| `GET /api/ext/funds/{ticker}/holdings` | 披露持仓 |
| `GET /api/ext/convertibles` | 当前导入快照 |
| `GET /api/ext/convertibles/template` | 空 CSV 模板 |
| `POST /api/ext/convertibles/preview` | `{csv_text, as_of}`，只校验 |
| `POST /api/ext/convertibles/import` | `{csv_text, as_of, expected_revision, confirmed:true}` |

基金错误：配置缺失 503、无效 Key 或权限不足 403、标的不存在 404、参数或不支持的类型 422、限流 429、网络或响应格式异常 502。供应商原始错误正文不会直接返回给前端。

## 开发与升级

新增代码主要位于：

- `backend/app/custom/funds/`
- `backend/app/custom/convertibles.py`
- `backend/app/services/convertibles_research.py`
- `frontend/src/custom/funds/`
- `frontend/src/custom/convertibles/`

核心接线只追加 `frontend/src/lib/api.ts` 的类型和请求，以及 `frontend/src/lib/queryKeys.ts` 的查询键。未来合并上游版本时重点复核这两份共享文件，并重跑扩展与数据源契约测试。不复制主页面、不覆盖主路由、不改变主数据源的默认路由。

功能回滚可以回退本分支的功能提交；导入数据单独存放，代码回退不应删除用户数据。

## 验证命令与限制

在安装仓库锁定依赖后执行：

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

2026-10-21 的最终验证：上述后端六个测试文件共 **167 项通过**；前端扩展注册及新增功能共 **18 项通过**；Ruff、TypeScript、Vite 构建和 `git diff --check` 通过。测试覆盖真实数值断言、单位日期归一、缺配置/无权限、无数据/异常响应、导入原子性、版本冲突与查询竞态。

独立临时数据目录中的完整应用 HTTP 联调也通过：缺 Key 返回 503；预览不写入；120/10/10 的价格得到 100/20/140；缺值保留；确认导入后可读取；旧版本确认返回 409；非 100 元面值被拒绝；两个前端地址均返回页面。测试记录没有进入用户数据或提交内容。

当前环境的 pnpm 外层会触发自动安装，受到运行环境限制；验证使用已安装的 `node_modules` 直接运行 Vitest、`tsc -b` 和 `vite build`，即 package script 的同一构建链。FastAPI TestClient 在隔离环境的线程事件循环中会挂起，使用可运行本地线程通信的执行环境后同一测试立即通过，未修改依赖或生产代码规避测试。

尚未使用真实扶摇 Key 验证线上数据。完整应用 HTTP 路由已作本地检查；浏览器与本地服务处于不同环境，连接被拒绝，因此桌面/窄屏和双主题的实际视觉检查仍待完成。源码分支适合继续联调，尚未打包发布新的桌面安装包。
