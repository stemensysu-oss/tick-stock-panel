# 多资产工作台 0.3.13 交付记录

日期：2026-10-22。开发基线：`feature/funds-convertibles` 的 `64eff881a98a69e0397c18e3918d1a654bf51b41`。

## 实现与边界

新增 `/multi-asset` 工作台，使用已有前后端 L2 扩展注册。包含套利股、封闭基金、ETF、现金管理、REITs、LOF、A/H、T+0 QDII、分红、新股、债券、指数共 12 个分类，保留原基金和可转债页面及存储。

已实现：后端分类/字段注册表、中文导览、分类清单、搜索、排序、自选、显示列、分页、详情、CSV 模板、导入预览及确认、版本冲突保护、原子保存、分类导出。支持保守的净值溢价、A/H 溢价、现金对价空间、明确期间股息率计算；日期、币种或必要输入不齐时返回未知。

新模块的数据状态只有用户导入、虚构演示或空清单，没有已核验实时 API。完整程序首次进入导入模式；单文件预览默认展示带显著标识的虚构样本。每类 3 条样本包含完整、对照和缺失输入场景，使用生产后端生成，未复制集思录截图行情。

完整[架构与阶段范围](multi-asset-workspace.md)、[功能与数据源矩阵](multi-asset-source-matrix.md)分别记录实现契约和后续来源候选。换股/供股权定价、全量公告、真实行情源和个人组合会计仍待后续开发。单个数据目录只支持一个后端写入进程。

## 实际验证

| 检查 | 结果 |
| --- | --- |
| 新模块及基金、转债、扩展、桌面、打包配置、版本、升级保护、开放 API 契约后端测试 | 194 项通过 |
| 新工作台及原基金、转债、前端扩展回归 | 47 项通过，12 个测试文件 |
| TypeScript 与生产 Vite 构建 | 通过；现有大型图表包体积提示仍存在 |
| 新 Python 文件 Ruff / `git diff --check` | 通过 |
| 后端锁文件一致性与冻结离线安装 | 通过；仅应用版本改变，第三方包版本保持不变 |
| 实际 Chromium `file://` 打开预览 | 通过，12 个分类各显示 3 条虚构记录 |
| 浏览器筛选、数值排序及缺值置后、自选、详情、导入/演示切换 | 通过 |
| 桌面深色/浅色与 390px 窄屏详情 | 通过，无页面横向溢出，宽表格在自身容器滚动 |
| 预览浏览器页面异常 / HTTP 请求 | 0 / 0 |
| 新 Windows 安装包、真实 Key、真实市场资料 | 本轮未验证 |

Windows 沙箱阻断 Python 异步事件循环的本机套接字，API 测试因此在沙箱外的隔离工作目录运行。旧测试有一处使用系统默认编码读中文文件，最终统一设置 `PYTHONUTF8=1` 后复核通过；未修改该旧测试。测试均使用临时资料，未接触现有 TSP 安装或实际用户数据。

## 复现

```powershell
cd backend
uv sync --frozen --extra dev --python 3.12
$env:PYTHONUTF8 = '1'
uv run --frozen pytest tests/test_multi_asset.py tests/test_custom_funds.py tests/test_custom_convertibles.py tests/test_convertibles_math.py tests/test_convertibles_research_v2.py tests/test_convertibles_sources.py tests/test_extensions.py tests/test_desktop_window.py tests/test_packaging_spec.py tests/test_version_source.py tests/test_upgrade_guard.py tests/test_openapi_contract.py -q

cd ../frontend
corepack pnpm install --frozen-lockfile
corepack pnpm exec vitest run src/custom/multi-asset src/custom/funds src/custom/convertibles src/extensions
corepack pnpm build
corepack pnpm build:multi-asset-preview
```

预览默认输出 `dist/TSP-multi-asset-preview.html`（仓库根目录），无需服务器，可直接用浏览器打开。构建器调用 `backend/.venv` 的 Python；可通过 `TSP_PYTHON` 指定其他已安装后端依赖的解释器。文件内包含真实页面及后端生成的虚构快照，并用 CSP 禁止网络连接；导入、导出及原模块跳转只在完整程序中可用。该预览不是安装器，不会升级旧 TSP。

## 升级与回退

应用版本更新到 0.3.13，后端项目/锁文件与 Windows 手动构建工作流默认版本同步；没有更新依赖包版本。重新生成锁文件时修正了原文件中 OpenAI 包最低版本元数据与现有项目声明不一致的问题（原记录 >=1.40，项目早已声明 >=1.66），并由 uv 规范化条件标记；实际锁定版本仍是原来的 2.38.0。主路由、后端生命周期、旧基金/转债模块均未替换。共享源码改动限于 API 客户端与查询键的增量接线。

继续在原功能分支追加提交，保留所有历史。合并上游前使用现有升级检查脚本，合并后运行上述契约回归。回退程序时保留 `data/multi_asset/workspace.json`，旧版本不读取该新增文件；原研究数据无需迁移。当前交付不包含新的 `.exe`，没有在用户电脑上安装或卸载任何程序。
