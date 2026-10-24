# Mac 上终端 Codex 正常，TSP 却提示不可用

终端与 Finder 启动的桌面程序不一定拥有同一份 PATH。原实现只在 Windows 补查 npm 和 Codex Desktop 安装位置，Mac 仅调用 `shutil.which('codex')`。因此即使终端执行 `codex --version` 成功，桌面启动的 TSP 也可能查不到同一文件。若 npm 启动脚本已找到、Node 不在桌面 PATH 中，原来的统一错误提示也会误写成“未找到命令”。

修复仍只接受固定的 `codex` 命令：先保留现有 PATH 解析结果，再补查 Homebrew、用户本地 bin、npm-global、Volta、默认 nvm/fnm/asdf 目录及 Codex.app。只检查固定安装目录中的文件和可执行权限，不执行用户的登录 shell、不加载 `.zshrc`，也不扫描整个用户目录。自定义安装前缀仍需另行核对实际路径。

`--version` 探测和正式 `exec` 统一使用子进程专用 PATH，其中保留 CLI 自身的 bin 目录供 `/usr/bin/env node` 查找，不改全局环境、不改登录资料。测试按钮仍只检查 CLI 能否启动，不应把通过解释为模型权限和实际生成已验证。

临时排查可先退出 TSP，再在已经能够运行 Codex 的终端直接启动应用内部程序（若应用位于其他目录，替换为实际路径）：

```sh
"/Applications/TSP.app/Contents/MacOS/TSP"
```

这样可让应用继承同一终端的环境。若测试由失败变为通过，可进一步确认是桌面与终端环境差异。定位具体 CLI 安装位置只需 `command -v codex`，无需提供认证文件、Token 或密钥。

回归使用临时目录模拟 Finder PATH 与 Homebrew/Node 管理器安装位置，没有使用真实账户；不把 Windows 上的路径模拟测试称为 Mac 原生实测。官方非交互方式见 [Codex exec](https://developers.openai.com/codex/noninteractive/)。
