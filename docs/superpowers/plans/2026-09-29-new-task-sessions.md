# New Task Sessions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在网页选择已有会话或新建独立 Session，持久加入左侧共享任务。

**Architecture:** 独立 SessionTasks 管理元数据候选、补充列表和幂等创建。Hub 继续负责单会话服务、队列和广播；HTTP 路由复用现有认证；原生 dialog 与独立脚本实现新任务操作。

**Tech Stack:** Python、标准库 JSON 原子写入、现有 Codex JSON-RPC、原生 JavaScript/CSS、pytest、Node test、Playwright。

**Spec:** docs/superpowers/specs/2026-09-29-add-shared-session-design.md

## Global Constraints

- 当前分支开发；不打包、不推送、不发布、不重启真实服务或 PHP。
- 元数据候选不恢复、不共享、不返回历史正文；添加已有会话不调用 thread/start。
- 共享采用现有项目密码权限，补充列表独立于私人 TOML，不能扩大文件预览范围。
- 新建只使用核实的项目目录和当前 permission_mode，不发送首条消息。
- 失败不可影响原会话；候选分页最多 50 项；重复创建 request_id 不得重复调用 RPC。

### Task 1: 元数据和持久化任务管理

**Files:** 新增 lan_codex_share/session_tasks.py、tests/test_session_tasks.py；修改 codex_client.py。

**Interfaces:** SessionTasks(path, client, workspace, register, shared_ids); restore(), candidates(query, cursor), projects(), add(session_id), create(project, request_id), close()。register(metadata) 向 Hub 注册未连接条目；shared_ids() 返回当前共享 ID。

- [x] 写失败测试：临时目录 FakeClient 的 list_threads/read_thread_metadata/create_thread 独立记录调用；assert tasks.add(id)["session_id"] == id；assert client.created == []；重新构造 manager.restore() 后同 ID 存在。
- [x] 运行 `.venv-desktop/Scripts/python.exe -m pytest tests/test_session_tasks.py -q`，确认缺少实现时失败。
- [x] 实现 UUID 校验、最多 10000 条元数据的短期缓存、50 条候选分页、项目目录核实、原子 JSON 写入和错误隔离。RPC 方法直接使用 thread/read includeTurns=false、thread/start，不调用 ensure_thread。
- [x] 创建前持久记录 `{request_id: {project, status: "pending"}}`；返回后写真实 ID；重试 pending 返回不确定错误，已知 ID 重试只添加，不重复创建。写入失败明确返回 ID。
- [x] 补充损坏文件、非法目录、并发去重、RPC 不确定结果、创建后保存失败、缓存分页和未泄露正文测试，运行到通过。

### Task 2: Hub、启动装配与认证路由

**Files:** 修改 session_hub.py、lan_main.py、lan_service.py、lan_web.py；新增 tests/test_session_tasks_web.py；扩展 tests/test_session_hub.py。

**Interfaces:** Hub.register_session(metadata), configure_tasks(tasks, factory)；HTTP GET candidates/projects，POST add/create。

- [x] 写测试：静态 Hub 注册第二个 metadata 后 thread_ids 包含两项，snapshot 原会话不连接第二项；snapshot 第二项调用 factory 一次；preview_roots 保持不变。
- [x] Run `.venv-desktop/Scripts/python.exe -m pytest tests/test_session_hub.py -q`。
- [x] 给 Hub 添加补充 metadata 集合，合并 resolve、摘要和项目导航，延迟连接与清理；restore 在初始会话启动完成后执行。静态服务摘要补 cwd，不改原默认会话。
- [x] 启动装配注入独立元数据 CodexClient、SessionTasks 和动态 service factory，复用现有 workspace/permission/state 路径规则。
- [x] 添加路由位于原 resolve_session_id 前，仍在认证后。GET 不返回历史；POST 仅使用明确字段、不向 RPC 透传额外参数；未知任务管理实例返回可理解错误。
- [x] HTTP 测试断言未知 ID 能经过 add 路由、不绕过登录/Origin/CSRF，运行相关 Python 回归。

### Task 3: 新任务弹框与左侧导航

**Files:** 新增 web/tasks.js、tests/javascript/tasks.test.cjs；修改 index.html、app.js、style.css、static_assets.py 和静态资源完整性校验。

**Interfaces:** window.LanTasks.mount({request, mutate, current, onAdded, onCreated, canSubmit})；app.js 提供现有认证包装、刷新与 selectSession。

- [x] Node 测试覆盖候选请求页、过期请求取消、非 HTTPS UUID 生成；先运行失败测试。DOM 纯文本与控件状态通过真实浏览器检查。
- [x] 原生 dialog 两种 radio 模式；已有会话使用搜索/项目组/无限滚动候选、选择或粘贴 ID；新建使用服务端 projects 下拉框。原生 focus trap、Esc 与关闭恢复焦点，错误用 role=status。
- [x] 左侧所有模式渲染完整 session 列表，隐藏重复顶部下拉框，保留释放/重连；创建切换前按 session 保存草稿及 File 引用，切回恢复。
- [x] GET AbortController 和代数校验；POST 不因关闭弹框而重复发起，创建 request_id 在不确定结果下保留，重试复用。
- [x] 为 tasks.js 加内容指纹静态资源，运行 Node 全套与静态资源 Python 回归。

### Task 4: 浏览器、文档与最终回归

**Files:** 新增 tests/fixtures/session_tasks_preview.py；修改 README、设计规格和本计划状态。

- [x] 使用 FakeClient/FakeService 和临时配置启动独立 loopback 测试页面，不连接真实 App Server。
- [x] Playwright 验证已有选择、搜索、新建、左右切换、文字/附件草稿恢复、两个页面同步；保存桌面/375px 截图并检查布局。按 ID 添加及错误输入另由 HTTP/存储测试覆盖。
- [x] README 说明候选隐私、两种操作、runtime 补充清单及配置范围关系；spec 状态标记完成。
- [x] 运行 `.venv-desktop/Scripts/python.exe -m pytest -q`（789 通过）、新 Node runtime 的 `node --test tests/javascript/*.test.cjs`（47 通过）、`git diff --check`。
- [x] 停止仅本次创建的测试浏览器/fixture，记录测试结果，保留当前分支本地代码交用户测试。

## 验证记录

- 原始失败测试确认缺少 SessionTasks、Hub 注册入口及 tasks.js 后，再逐项补实现。
- 浏览器验证采用 tests/fixtures/session_tasks_preview.py 的模拟元数据和服务；未创建真实 Codex Session、未发真实 AI 请求。
- 同项目路径别名分组、创建后原草稿/待发送 PNG 恢复、新会话空草稿、多页面只同步不跳转均通过实际操作验证。
- 截图：output/playwright/new-task-desktop.png、new-task-create.png、new-task-mobile.png、new-task-sidebar.png（本地忽略文件）。
- 浏览器仅有原有 favicon.ico 404 和密码表单提示，无新增脚本异常。测试脚本修正过 searchbox 定位及异步等待；附件测试 fixture 的请求限额调高后验证通过。
