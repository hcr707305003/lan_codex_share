# Web Task Notification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 默认关闭、可由 TOML 或控制台开启的 Web 任务结束常驻提示。

**Architecture:** LAN 配置经 auth/status 传递一个布尔值；独立 notifications.js 跟踪当前 Session 的 turn 终态并渲染可手动关闭卡片。现有 SSE/刷新仍是唯一状态来源，历史分页不进入跟踪器。

**Tech Stack:** Python、原生 JavaScript/CSS、PySide6、pytest、Node test runner。

**Spec:** docs/superpowers/specs/2026-09-16-web-task-notification-design.md（用户已确认，包含控制台开关）。

## Global Constraints

- 在当前 main 开发，保留脏工作区；不提交、打包或发布。
- 不启停现有 Share、隧道和 PHP 服务。测试只用隔离配置、假服务。
- 默认 false，严格布尔值；不改真实配置，不增加依赖。
- 当前会话、页面内手动关闭；不加声音、系统通知或全 Session 监听。

## Task 1：配置与控制台同源开关

Files: lan_codex_share/lan_config.py、lan_main.py、lan_web.py、desktop/config_page.py；tests/test_task_notification_config.py。

Interfaces: `LanConfig.notify_on_task_complete: bool = False`；`LanWebApplication(..., notify_on_task_complete=False)`；GET /api/auth/status 返回同名 bool。

- [x] 写配置与桌面测试并运行，预期字段不存在/控件不存在而失败。
  ```python
  assert load_lan_config(path).notify_on_task_complete is False
  page.editors['notify_on_task_complete'].setChecked(True)
  page.save()
  assert load_lan_config(path).notify_on_task_complete is True
  ```
- [x] 加严格类型验证、构造传参、auth/status 标志，测试 true/false 和字符串、整数、数组拒绝。
  ```python
  notify = data.get('notify_on_task_complete', False)
  if not isinstance(notify, bool):
      raise LanConfigError('notify_on_task_complete 必须是布尔值')
  ```
- [x] 表单字段新增 checkbox 类型，初始化缺省 false，连接 toggled 写入 updates；不触发保存或服务操作。重新加载和原始编辑均从 ConfigDocument 获取。
- [x] 运行 `.venv-desktop/Scripts/python.exe -m pytest tests/test_task_notification_config.py tests/test_lan_config.py tests/test_lan_web.py -q`，全部通过。

## Task 2：实时终态跟踪、手动关闭卡片

Create: lan_codex_share/web/notifications.js、tests/javascript/notifications.test.cjs；Modify: web/app.js、index.html、style.css、static_assets.py、lan_web.py。

Interfaces: `TaskNotifications(container)`；`setEnabled(bool)`、`reset()`、`update(snapshot)`。`TaskCompletionTracker.update(snapshot)` 返回新通知数组，`reset()` 清基线。Node 导出两类供测试，浏览器脚本在 app.js 前加载。

- [x] 写 Node 测试：首次快照历史不弹、运行转各终态、快速新 turn、重复/重连、Session 切换、断线不误判、独立实例、关闭后不重复。
  ```javascript
  const tracker = new TaskCompletionTracker();
  assert.equal(tracker.update(snapshot('inProgress')).length, 0);
  assert.equal(tracker.update(snapshot('completed')).length, 1);
  assert.equal(tracker.update(snapshot('completed')).length, 0);
  ```
- [x] `node --test tests/javascript/notifications.test.cjs` 确认新增模块缺失导致失败。
- [x] 实现按 Session/turn ID 的基线与去重，复制简单状态值防止 SSE 共享对象修改；只认明确终态，不按 idle 猜测；不对历史分页调用 update。
- [x] 卡片 textContent、显式关闭按钮、单一 aria-live 容器；限高滚动，无计时删除、无自动 focus。跟随 composer 上缘定位，窄屏限宽，复用 CSS 颜色。
- [x] auth/status 配置应用；render 在 version 早退前跟踪；selectSession 和登出清空；短暂重连不清空。新资源进入静态指纹缓存、资源校验、脚本顺序。
- [x] 运行 Node 测试和静态资源回归；用假 DOM 校验安全文本、关闭互不影响、无抢焦点。

## Task 3：文档与回归

Modify: lan_config.example.toml、README.md、DESKTOP.md、上述 plan。

- [x] 示例/说明增加 `notify_on_task_complete = false`，说明控制台路径、手动关闭、重启刷新生效和当前 Session 边界。
- [x] 执行 `.venv-desktop/Scripts/python.exe -m pytest -q` 及 `node --test tests/javascript/*.test.cjs`；`git diff --check`。
- [x] 用独立假数据进行浏览器或离线布局检查（桌面、窄屏）及 Qt 开关检查，记录可验证结果和限制，不连接真实任务。
- [x] 自审规格覆盖；标记完成，交付配置方法及需用户手动重启 Share、刷新网页；保持未发布。

## Task 4：用户追加的目录列表

Create desktop/directory_list.py；Modify desktop/config_page.py；Test tests/test_desktop_directory_list.py。

- [x] 独立 `DirectoryListEditor(values, base_dir)`，`changed = Signal(list)`，`values()` 返回原字符串列表；`add_directory()` 调用系统目录选择器并委托 `add_path(path)`，`remove_selected()` 只移除列表项。
  ```python
  relative = Path(os.path.relpath(chosen.resolve(), base_dir)).as_posix()
  # ValueError (不同盘符) 时 chosen.as_posix()；以解析路径去重。
  editor.changed.connect(lambda values, k=key: self.updates.__setitem__(k, values))
  ```
- [x] 测试选目录取消、不重复、添加/删除/保存不删文件，读取与写回相同数组，原始配置可编辑；`.venv-desktop/Scripts/python.exe -m pytest tests/test_desktop_directory_list.py -q`。

## Task 5：用户追加的外部 FRP 关闭

Modify desktop/external_tunnels.py、tunnel_monitor.py、window.py；Test tests/test_external_frpc_control.py、test_desktop_tunnel_ui.py。

- [x] `TunnelIdentity(pid, created_at, executable, argv, config_path)` 不在 repr 展示命令行，TunnelState 新增可选 identity。仅匹配单个普通 frpc 赋身份，Windows 服务、多实例、未匹配继续拒绝。
- [x] `close_external_frpc(settings, identity)` 先 inspect_tunnels 重验，再对目标 psutil.Process 重验指纹和配置路径，terminate 后 wait(timeout=5)；超时只报告不递归、不自动升级杀进程。
- [x] monitor 新增 busy/generation/关闭异步结果和日志信号；旧扫描结果忽略。窗口按钮、确认框/退出保护接入，成功或失败后都重扫。
- [x] 测试正常目标关闭一次、PID 复用/配置变化/Windows 服务/权限不足不关闭、仅目标终止、超时提示、UI 默认取消且不自动关闭外部进程。所有测试用假进程。

## 自审

覆盖默认值/校验、桌面同源配置、SSE 与刷新去重、历史边界、常驻关闭、安全文本及回归。用户选择原地开发与未发布优先于技能默认提交步骤；本轮在当前会话内执行，不派发子代理。

## 执行结果

- 最终全量 pytest：609 passed（50.86 秒）；Node 独立套件：33 passed；git diff --check 通过。
- 配置默认关闭、严格布尔校验、控制台开关和目录列表已完成，保存只写配置。
- 实时提示复用 SSE；首次基线/手动关闭/重连去重、明确终态和登录配置时序已覆盖。
- 外部 FRP 确认关闭只针对单个身份匹配的普通进程；Windows 服务、模糊身份及其他隧道仍保护。
- 隔离浏览器检查通过：桌面与 375×812、输入焦点保留、三种结果、逐条关闭及刷新不重弹。控制台 900×640 四主题、目录列表、保存按钮和确认框已用离线模拟状态检查。
- 测试截图位于已忽略的 output/playwright/notifications；浏览器的 favicon 404 为原有缺失图标，不影响功能。测试浏览器和模拟 HTTP 服务已关闭。
- 未修改真实配置，未启停现有 Share/FRP/Cloudflare/PHP；保持当前分支，未提交、构建或发布。
