# Cloudflare Form Implementation Plan

> **For agentic workers:** Use executing-plans inline. No delegation or worktree changes.

**Goal:** 为本地 Cloudflare YAML 提供四字段表单与高级文本模式。

**Architecture:** 独立 YAML 标量编辑器保留原始文本；独立 Qt 表单持有草稿，ConfigPage 负责保存和模式切换，保持原有同步流程。

**Tech Stack:** Python、PySide6、PyYAML、pytest。

**Spec:** docs/superpowers/specs/2026-09-17-cloudflare-form-design.md

## Global Constraints

- 保存才写配置，不启动、停止、重启服务；不提交打包发布。
- 保留其他规则和注释；复杂结构回退高级模式。

### Task 1: YAML 局部编辑

- [x] 写 `tests/test_cloudflare_form_data.py`，验证 `update_fields(text, updates, rule_index)` 保留未知字段、注释、Windows 路径，并拒绝非法域名、URL、锚点。
- [x] 先运行测试验证模块不存在；新增 `desktop/cloudflare_form_data.py`，使用 `yaml.compose` 节点位置替换对应标量，修改后重新解析校验，失败不返回新文本。
- [x] 运行数据层测试。

### Task 2: Qt 表单与集成

- [x] 写 `tests/test_cloudflare_form_ui.py`，覆盖加载、文件选择、入口切换、高级模式、保存、副本、冲突和 Token 提示。
- [x] 新增 `desktop/cloudflare_form.py`：`CloudflareForm(text, config_path, lan_path, token_mode)`；`apply()` 返回合并草稿的 YAML，`dirty()` 返回未保存状态，`changed` 提示父页面。
- [x] 接入 `desktop/config_page.py`：CF 加载启用表单切换，应用草稿后走原保存逻辑；创建示例取 Share 端口，状态仅在内存变化。
- [x] 更新 DESKTOP.md，运行定向和全量测试、四主题离屏截图，git diff --check。
- [x] 用户追加：README 补充桌面功能、启动方式与两张演示配置截图；截图不包含实际路径、密钥或真实服务状态，不推送发布。

验证：最终完整 pytest 722 项通过（57.76 秒）。四主题 × 两种窗口尺寸检查通过；已检查 README 两张演示截图并验证图片路径。保留当前分支改动，未提交、打包、发布或操作真实服务。
