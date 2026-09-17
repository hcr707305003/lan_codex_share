# Share → FRP / Cloudflare Port Sync Implementation Plan

> **For agentic workers:** Use executing-plans inline, without subagents.

**Goal:** 保存 Share Web 端口时同步对应 FRP localPort 和 Cloudflare YAML service 端口。

**Architecture:** 独立快照 proposal 负责匹配和写入；ConfigPage 在 Share 保存前准备，保存后应用并显示部分成功状态。

**Tech Stack:** Python、tomlkit、PySide6、pytest。

**Spec:** docs/superpowers/specs/2026-09-17-share-frp-port-sync-design.md

## Global Constraints

- 当前分支实施，保留已有改动；不操作运行服务、不提交发布。
- 仅更改匹配旧 Share 端口的 TCP loopback localPort 或 HTTP loopback service；不改其他端口或规则。

### Task 1: 快照与匹配

- [x] 新增 `tests/test_tunnel_port_sync.py`：`prepare_port_sync(path, kind, old_port, new_port).apply()` 更新匹配项，验证两类隧道、旧端口、过滤、注释、并发及写权限失败。
- [x] 运行测试确认缺少模块导致失败。
- [x] 新增 `desktop/tunnel_port_sync.py`：验证两端端口，读取并验证配置，筛选规则。FRP 用 tomlkit 保留格式；YAML 用源节点字符位置替换 service 标量保留注释及其他字段，通过 ConfigDocument 保存。
- [x] 运行测试确认通过。

### Task 2: 保存流程

- [x] 新增 `tests/test_tunnel_port_sync_ui.py`：正常/原始文本/副本/失败/缺配置/自定义配置路径/Token 跳过，以及 tunnel_port_synced 信号。
- [x] 修改 `desktop/config_page.py`，在 Share 保存前获取 proposal，保存后应用；错误返回部分成功说明，不调用进程 API。
- [x] 补充 `DESKTOP.md` 的同步边界和手动重启说明。
- [x] 运行新增测试、现有入口同步测试、完整 pytest 和 git diff --check。

验证结果：新增及相关入口 UI 测试 52 项通过；完整 pytest 691 项通过（56.05 秒）。未打包、提交、发布或操作实际运行服务。
