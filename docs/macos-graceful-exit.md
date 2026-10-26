# Mac 退出修复（0.3.23）

触发：⌘Q 或应用菜单退出。pywebview 6.2.1 的 Cocoa AppDelegate 返回
NSTerminateNow，使 NSApplication 在原生事件循环内结束进程，绕过 TSP 的
Python finally。旧桌面入口也没有保留 uvicorn 的关闭控制权，红色关窗后直接
返回，仍有后台线程运行。这是已确认的退出生命周期缺口；用户 Mac 的确切
崩溃栈仍须以其系统报告为准。

本次为 L3 最小核心入口修改，不更改行情、计算公式、API 或存储格式。

- Mac 专用适配器持有独立 AppDelegate：先取消原生直接终止，在下一次主线程
  事件循环执行 performClose:，保留 windowShouldClose 的取消语义。
- 窗口循环返回后请求 uvicorn.should_exit，等待现有 FastAPI lifespan 停止后台
  服务及事件循环，最后移除单实例锁。SSE 请求排空上限 5 秒，整体等待 45 秒；
  超时明确记错并返回非零，不把强制结束当成验证通过。
- 不使用 os._exit、不禁用 macOS 崩溃提示、不删除系统崩溃报告。
- Mac 安装验证新增实际 ⌘Q、红色关闭按钮和系统 Quit 请求：必须零退出码、
  当前这次退出的清理日志、端口关闭、锁移除，且没有新增匹配的系统崩溃报告。
  只有失败后的清场才允许终止测试进程，不能替代正常退出的通过结果。
- 云端另运行固定 0.3.22 入口作对照，结果单独记录；这是源码对照，不能冒充
  旧安装包测试。原生新安装包仍执行两次安装/替换和真实数据检查。

适配器依赖 pywebview 6.2.1 的 _shared_app_delegate 接入点，位于单独 Mac
模块中。上游升级时需复核该点及三条退出路径。Windows 不加载 Cocoa 适配器，
复用服务停止流程。配置与研究数据兼容 0.3.22；安装替换不删除用户数据。

参考上游源码：https://github.com/r0x0r/pywebview/blob/6.2.1/webview/platforms/cocoa.py
