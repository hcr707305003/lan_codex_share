# Desktop Session List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 控制台列表化管理 Session ID，保留三种模式和安全保存边界。

**Architecture:** SessionListEditor 管理模式、列表和未添加草稿；ConfigPage 将其明确变更合入现有原子保存；ConfigDocument 增加显式顶层字段移除。后端 Session 发现/连接保持不变。

**Tech Stack:** PySide6、Python、tomlkit、pytest。

**Spec:** docs/superpowers/specs/2026-09-17-desktop-session-list-design.md（已确认）。

## Global Constraints

- 当前 main、保留已有改动，不提交/打包/发布，不启停真实服务。
- 三模式：指定会话非空数组、共享全部空数组、自动单会话删除两个 Session 字段。
- 不连接或扫描会话；移除只改配置；复制必须显式点击。
- 保留原始编辑、外部文件修改检测、注释和未知配置项；不新增依赖。

## Task 1：列表控件与解析

Create `lan_codex_share/desktop/session_list.py`、`tests/test_desktop_session_list.py`。

Interfaces: `parse_session_input(text) -> list[str]`；`SessionListEditor(data, parent=None)`；`changed` 信号；`dirty() -> bool`；`changes() -> (dict, tuple[str, ...])`；`mark_applied()`；`values()`；`add_input()`、`remove_selected()`、`copy_selected()`。公开 mode（QComboBox）、list、input 供测试与交互。

- [x] 写解析和控件测试，确认缺少模块导致失败。
  ```python
  assert parse_session_input(' a, b\na ') == ['a', 'b']
  editor = SessionListEditor({'session_ids': ['a']})
  editor.list.setCurrentRow(0)
  editor.remove_selected()
  with pytest.raises(ValueError): editor.changes()
  ```
- [x] 实现：加载新旧字段时校验冲突/类型，缺省为 auto；changed_config 状态只在明确改变模式或列表后设置；未添加输入计入 dirty。
- [x] 添加时全量解析成功后才合并，使用 set 去重保序；JSON 非字符串、损坏 JSON、内部空白拒绝。不限制 UUID 版本。错误保留原列表和草稿。
- [x] 指定列表为空或尚有非空输入时 changes() 报错；切换模式有输入草稿时回退选择；指定列表在本次表单模式切换中保留。
  ```python
  # 明确编辑后的配置补丁：
  return ({'session_ids': ids}, ('session_id',))  # selected
  return ({'session_ids': []}, ('session_id',))   # all
  return ({}, ('session_ids', 'session_id'))     # auto
  ```
- [x] `.venv-desktop/Scripts/python.exe -m pytest tests/test_desktop_session_list.py -q` 通过。

## Task 2：配置保存集成

Modify `desktop/config.py`、`desktop/config_page.py`；Test `tests/test_desktop_session_config.py`。

Interfaces: `ConfigDocument.update_fields(text, updates, proxy_index=0, *, remove_fields=())` 显式移除顶层字段后再应用 updates；原调用保持兼容。

- [x] 写测试缺省/空数组/非空列表/旧格式、保存前不改文件、删空保护和失败保留草稿。
- [x] FIELDS 中 session_ids 类型改 sessions，使用完整 data 初始化控件；不把无字段推成空数组。
- [x] dirty() 在表单模式下检查 SessionListEditor.dirty；apply_form() 先完整校验，再合并所有字段修改、一次 update_fields，成功后 mark_applied。控件不通过 updates 中的 None 表示删除。
  ```python
  session_updates, remove_fields = editor.changes()
  result = document.update_fields(raw, {**updates, **session_updates}, remove_fields=remove_fields)
  ```
- [x] 重新加载/原始编辑建立新控件基线；没有明确 Session 修改时不迁移旧字段；保存失败保持 raw 与界面草稿、原磁盘文件不变。
- [x] `.venv-desktop/Scripts/python.exe -m pytest tests/test_desktop_session_config.py tests/test_desktop_config.py tests/test_task_notification_config.py tests/test_desktop_directory_list.py -q` 通过。

## Task 3：文档与验证

Modify README.md、DESKTOP.md；必要时只为新控件补主题样式。

- [x] 文档说明三模式、复制/移除不操作真实 Session、批量格式、未添加草稿、空列表保护、保存后手动重启生效。
- [x] 隔离 Qt 检查四主题、900×640 与 1280×800、长 ID、错误提示、底部保存可见。截图放已忽略 output/playwright/session-list，临时脚本放 .superpowers。
- [x] 全量 `.venv-desktop/Scripts/python.exe -m pytest -q`，`git diff --check`；复核运行/发布边界，记录最终结果并交付。

## 自审

覆盖批量输入、控件行为和配置语义；不需要外部 API。按用户原地开发、不发布的要求跳过技能默认提交；当前会话内执行，不派发子代理。

## 实施结果（2026-09-17）

- 新增 SessionListEditor 与批量解析，接入表单 dirty、原始配置切换、显式字段删除和原子保存；更新 README/DESKTOP。
- 先验证缺模块/缺控件接口失败，再实现；控件测试 24 项、含保存流程的定向测试共 54 项通过。
- 完整回归：`641 passed in 54.07s`；`git diff --check` 通过。
- Qt 离屏检查四套主题、900×640/1280×800、ID 展示、错误批次保留和保存按钮可见；临时脚本和截图均已忽略，不连接真实服务。
- 当前 main 与已有改动保持原位；未修改私人配置、未启停服务、未提交/推送/打包/发布。
