# Workspace Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 通过文件夹对话框配置工作目录。

**Architecture:** WorkspacePicker 管理路径展示与选择；changed(str) 连接 ConfigPage 现有 updates/保存流程；原始编辑不变。

**Tech Stack:** Python、PySide6、pytest、PyInstaller。

**Spec:** docs/superpowers/specs/2026-09-17-workspace-picker-design.md

## Global Constraints

当前 main，保留已有修改；不启停真实服务、不写私人配置，不推送/发布；新包独立目录。

## Task 1：控件、接线和验证

Create `lan_codex_share/desktop/workspace_picker.py`, `tests/test_desktop_workspace_picker.py`；modify `desktop/config_page.py`, `DESKTOP.md`。

接口：`WorkspacePicker(value, base_dir)`、`choose_directory()`、`text()`、`changed(str)`；公开 path（只读 QLineEdit）和 browse（QPushButton），feedback（QLabel）。

- [x] 写测试并运行确认缺模块失败：选择中文目录、取消/同目录、跨盘 fallback、目录不存在、保存前磁盘不变、保存/原始模式往返。
  ```python
  picker.choose_directory()  # QFileDialog 返回 monkeypatch 的目标目录
  assert picker.text() == '中文 project'
  assert changed == ['中文 project']
  ```
- [x] 实现原生 getExistingDirectory；以配置父目录解析旧值；存在且不同才发 changed；os.path.relpath 遇跨盘 ValueError 用绝对路径。
  ```python
  value = Path(os.path.relpath(chosen, self.base_dir)).as_posix()
  self.path.setText(value)
  self.changed.emit(value)
  ```
- [x] FIELDS workspace 改 workspace 类型；实例化时传配置父目录，changed 接 field_changed(key, 'str', value)。不改后端解析。
- [x] `.venv-desktop/Scripts/python.exe -m pytest tests/test_desktop_workspace_picker.py -q`；更新使用文档；Qt 离屏检查四套主题、长路径和按钮可见。
- [x] 全量 pytest 与 git diff --check。使用原 spec 打到唯一 dist/build 目录，package_release --with-desktop 输出唯一 release 目录，smoke_desktop_distribution 验证；解压供用户双击，旧包不动。

自审：取消/无效/跨盘/未保存规则均有对应步骤。不派发子代理；本地包是用户预览流程的继续，不创建版本标签。

追加需求：用户要求高级 TOML 文件编辑。复用现有完整文本编辑器，将入口明确为「高级文件编辑 / 返回表单编辑」，保留敏感内容提示、表单草稿同步、语法校验与未知字段/注释；新增 `tests/test_desktop_advanced_config.py` 覆盖 LAN/FRP 双向切换与错误文本保留。此项一起进入最终本地测试包。

## 完成记录

- 工作目录选择器、FRP 随机命名及高级编辑入口一并完成；当前树完整测试 `653 passed in 54.50s`。
- 四套主题小窗口与长路径离屏截图、FRP 名称和高级 TOML 编辑截图已检查；测试资源均在忽略目录。
- `git diff --check` 通过。Windows 本地包位于 `release/local-preview-config-20260917-1789607530/`，GUI/CLI 解压启动及默认/显式配置路径 smoke 通过；同时提供已解压目录。
- 未覆盖旧包、未改私人配置、未启停真实服务、未提交/推送/发布；版本号不变，仅本地预览。
