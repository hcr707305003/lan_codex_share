# FRP Random Name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新建 FRP 配置随机命名，现有配置显式重新生成。

**Architecture:** ConfigPage 生成模板时调用 uuid4 名称工具；ProxyNameEditor 管理当前名称展示和重新生成，沿用选中代理字段更新流程。

**Tech Stack:** Python uuid、PySide6、pytest。

**Spec:** docs/superpowers/specs/2026-09-17-frp-random-name-design.md

## Global Constraints

当前 main，不改私人配置、不启停服务、不提交发布；名称避免本地重复，不宣称已校验 frps 全局唯一。

## Task：随机名称

Create `desktop/proxy_name.py` 与 `tests/test_desktop_proxy_name.py`；modify `desktop/config_page.py` 和 DESKTOP.md。

接口 `new_proxy_name(existing=()) -> str`；`ProxyNameEditor(value, existing)`，`changed(str)`，`text()`，`regenerate()`。

- [x] 测试模板每次生成不同，旧名称无操作不变、手动重新生成只修改选中项。
  ```python
  assert new_proxy_name() != new_proxy_name()
  editor.regenerate()
  assert editor.text().startswith('codex-share-')
  ```
- [x] new_proxy_name 循环生成 UUID4.hex 并排除 existing；只读 QLineEdit + 重新生成按钮，仅 changed 更新草稿。
- [x] create_example 的 frp 模板通过 document.update_fields 改 proxies.name 后展示；新增 name 表单行，changed 写 updates 并刷新当前下拉标题；切换代理仍先 apply_form，保存沿用原子校验。
- [x] 文档更新并定向/全量 pytest；随工作目录选择器一起 Qt 离屏检查和新建本地包验证。

自审：没有默认自动重命名旧配置，没有代理端口分配扩展。按既有授权当前会话执行，不另建分支或派发代理。

完成：新示例 UUID 随机名称、现有代理显式重新生成、本文件内重名排除与选中代理隔离均通过测试。最终完整回归 653 项通过，随 `local-preview-config-20260917-1789607530` 本地包交付，未发布。
