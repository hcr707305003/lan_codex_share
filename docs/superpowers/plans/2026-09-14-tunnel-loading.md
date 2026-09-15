# Tunnel Loading Optimization Implementation Plan

> **For agentic workers:** Execute inline using executing-plans, preserving the existing local checkout. No automatic commit, push or release.

**Goal:** 减少重复静态资源回源及每次实时更新的额外快照请求。

**Architecture:** 静态资源白名单生成内容哈希路径和 ETag；HTML 始终 no-store 引用当前指纹。新的 SSE delta 模式首次发送最近 20 轮，后续仅传变化字段、消息和文字追加；保留旧 update 模式兼容，重连发送新基线。

**Tech Stack:** Python 3.11 标准库、原生 JS、pytest、Node test、隔离 Playwright。

**Spec:** 用户批准静态资源内容指纹缓存和实时增量推送；代码变化更新资源 URL，刷新已打开页面才使用新版，不强制刷新或打断任务。

## Global Constraints

- 仅改 lan_codex_share；不改 Tunnel 配置、不管理业务服务。
- 仅 app.js/history.js/realtime.js/style.css 可公共缓存一年 immutable。
- HTML、API、图片、预览、下载、代理适配脚本继续 no-store；新 SSE 使用 no-store, no-transform。
- 新流必须先验证密码和 Session，再发送基线；切换任务关闭旧流、丢弃旧请求，失配补新基线。

### Task 1: Content fingerprints

Files: static_assets.py、lan_web.py、tests/test_static_assets.py。

- [x] 用临时静态目录测试 `assets.url('app.js')` 内容改动后变化；同一 URL 只返回同一内容，错误哈希 404。
- [x] 实现只读资源清单：记录 mtime/size，变化重新读取和计算 SHA-256，最多保存 16 个近期指纹内容。
- [x] 首页替换静态引用；指纹路径支持 GET/HEAD/ETag 304，公共缓存只应用到该白名单。
- [x] 检查无登录也可读取纯静态资源，所有私有数据仍不能公共缓存。

### Task 2: Delta SSE

Files: stream_delta.py、lan_web.py、web/realtime.js、web/app.js、web/index.html；tests/test_stream_delta.py、tests/javascript/realtime.test.cjs。

Interface: SnapshotDelta.next(snapshot) -> {event, data}; event snapshot carries sequence/snapshot; delta carries base/sequence/fields/thread_fields/order/turns. Message text append requires matching baseline. StreamSnapshot.apply(event, data) reconstructs a bounded 20-turn snapshot or rejects invalid sequence.

- [x] 测试首次基线、无变化、追加文本、更正文本、过程计数、队列/模型/导航变化、移除字段、历史世代重置。
- [x] 在 `/api/events?mode=delta&session_id=...` 先订阅再取首屏快照，合并队列信号，每条连接维护独立增量基线；原 update 模式不变。
- [x] 客户端建立独立基线，直接渲染 SSE 数据；活动流期间操作完成不再 GET 快照。断线兼容性读取不能覆盖较新的推送。
- [x] 测试连接认证、非法 Session、流重连、双浏览器、Session 切换和原分页接口。

### Task 3: Verify and document

- [x] 接入 Node 回归，运行全部 pytest 及 `git diff --check`。
- [x] 用合成 Session 的隔离浏览器验证缓存命中、基线后文字流回复无 `/api/snapshot` 请求、断线及切换任务不串数据。
- [x] README 说明内容变化/重启/刷新、缓存安全边界及仍存在的链路延迟。

## Validation results

- 全量回归：285 passed；包含 Node 客户端增量协议及 Python/JS 联合往返测试。
- 隔离浏览器：合成 2000 轮历史，第二页面四个指纹资源均命中浏览器缓存；稳定推送期间无额外快照请求，按需分页正常。
- 双页面同步、断线期间新增回复补齐且不重复、Session 切换、过程展开收起及移动端布局验证通过。
- 未修改 Cloudflare 配置，未重启正在运行的共享程序或业务服务，未提交、推送或发布。公网 CDN 命中和实际链路改善需更新运行程序后观察。
