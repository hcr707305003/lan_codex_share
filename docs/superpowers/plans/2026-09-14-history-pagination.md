# History Pagination Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan task-by-task in the current approved local workflow. No release or push.

**Goal:** 浏览器只获取和渲染需要的会话历史，完整历史和后台任务不丢失。

**Architecture:** Projection 提供轻量分页快照和过程分页；Service/Hub/Web 透传经校验的读取参数。独立 history.js 管理页面缓存、游标和 DOM 复用，app.js 保留现有消息渲染及交互。

**Tech Stack:** Python 3.11、原生 JavaScript、pytest、Node test、Playwright。

**Spec:** ../specs/2026-09-14-history-pagination-design.md

## Global Constraints

- 仅改 lan_codex_share；不修改个人配置，不操作业务服务。
- 每页默认 20 轮，服务端最多 50 轮；过程每页 20 项。
- 不删除完整记录，不发布或推送。

### Task 1: 分页数据契约

Files: session_projection.py、lan_service.py、session_hub.py、lan_web.py；tests/test_history_pagination.py。

Interfaces: snapshot(history_limit=None, before=None) 保持内部完整读取兼容；history_page(limit=20, before=None) 返回 thread/history；activities(turn_id, epoch, before=None, limit=20) 返回 items/history/revision。

- [x] 添加 2000 轮测试，断言 `len(projection.history_page()['thread']['turns']) == 20`，过程正文不在快照中。
- [x] 运行测试确认尚无 API；实现游标校验、先切片复制、轮次版本和世代。
- [x] 透传 Web 参数，非法参数返回 400；测试密码及 Session 隔离、追加与重同步游标。
- [x] 运行相关 pytest，检查完整 snapshot 旧测试保持通过。

### Task 2: 浏览器增量时间线

Files: web/history.js、web/app.js、web/index.html、web/style.css；tests/javascript/history.test.cjs。

Interfaces: HistoryTimeline({root, renderTurn, fetchPage, onError})，update(snapshot)、reset()；turn carries history_revision/activity_count; history carries epoch/start/end/total/before。

- [x] 测试覆盖同版本节点复用、旧消息前插、重置世代及旧异步结果失效。
- [x] 实现最新页合并、上滑到顶自动加载、失败重试按钮、回到最近消息、锚点补偿和 Session 缓存清理。
- [x] 过程保持原生 details，展开才请求过程页，分页查看更早项，活跃页更新；图片设置 loading=lazy、decoding=async。
- [x] SSE 合并刷新，现有发送、队列、文件预览测试通过，浏览器验证工具交互。

### Task 3: 验证和文档

Files: tests/test_markdown_renderer.py、README.md；output/playwright/ 下临时浏览器夹具不提交。

- [x] 将 Node 测试接入 pytest；运行 `.venv/Scripts/python.exe -m pytest -q`。
- [x] 隔离合成数据 HTTP 服务测试实际浏览器：首屏 20、翻页 40、过程初始零正文、展开后加载、流式节点复用、375px、滚动稳定。
- [x] README 说明首屏分页、过程按需加载、完整历史保留以及需要重启共享程序。
- [x] `git diff --check`、核对仅项目文件，交付本地自测，不发布。

## 验证结果

- 完整回归：278 passed（包含 Node 渲染测试）。
- 本机隔离浏览器、2000 轮合成数据：首屏约 6.8 KB，首次显示约 124 ms；不代表真实公网延迟。
- 已验证过程最新页/更早页各 20 项、折叠释放正文、执行中更新、完成后折叠、消息节点复用、旧消息前插锚点以及 Session 切换。
- 按用户追加要求改为上滑到顶自动加载，新增重复滚动合并和失败暂停自动请求测试；真实浏览器无须点击即可从 20 轮加载到 40 轮。
- 完整历史仍保留在服务器；源码改动需要用户重启共享程序后刷新浏览器。本次未操作真实业务服务、未提交推送或发布。
