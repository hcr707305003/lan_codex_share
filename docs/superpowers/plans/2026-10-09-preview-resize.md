# Preview Resize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拖动右侧文件预览面板左边界调整宽度，记忆宽度并可重置。

**Architecture:** 独立原生 JS 模块计算宽度边界并管理指针、键盘、存储及生命周期。既有 Grid 和浮层读取同一个 CSS 变量，文件加载逻辑不参与拖动。

**Tech Stack:** JavaScript Pointer Events、CSS Grid、localStorage、node:test、pytest、隔离浏览器测试。

**Spec:** `docs/superpowers/specs/2026-10-09-preview-resize-design.md`

## Global Constraints

- 当前分支开发，保留未提交的 XLSX 修复；只修改本功能文件。
- >=1200px 三栏：预览最小 360px，最大为视口减实际侧栏减 360px 聊天区；默认 clamp(420px,45vw,760px) 后再约束。
- 821–1199px 浮层：最小 360px，最大视口减侧栏，默认最高 640px。<=820px 全屏、不显示拖动条、不覆盖偏好。
- 左拖放大，右拖缩小；方向键 20px，Home/双击重置。存储失败不影响交互。
- 不放宽 CSP、不重新加载预览内容、不启动/重启用户服务、不推送或打包发布。

## Task 1: 独立尺寸控制器

**Files:** 创建 `lan_codex_share/web/preview-resize.js`、`tests/javascript/preview-resize.test.cjs`。

**Interfaces:** CommonJS/browser 双出口，公开 `bounds(viewport, sidebar)` 和 `createPreviewResize({shell,panel,handle,window,storage})`；后者返回 `{refresh,cancel,destroy}`。storage 可缺省，访问 window.localStorage 本身也必须捕获异常。

- [ ] 先建立尺寸与故障存储测试，执行 `node --test tests/javascript/preview-resize.test.cjs` 确认缺少模块导致失败。

```javascript
assert.deepEqual(bounds(1440,248), {min:360,max:832,defaultWidth:648,mobile:false});
assert.equal(bounds(1000,248).defaultWidth,640);
assert.equal(bounds(375,248).mobile,true);
```

- [ ] 实现边界和偏好读取：只接受有限正数，使用 `Math.min(max, Math.max(min, preferred))`。无偏好时使用当前布局默认值；窗口变化不保存约束后的偏好。
- [ ] 实现控制器，宽度通过 `shell.style.setProperty('--preview-width', width+'px')` 写入，不能使用 setAttribute('style',...) 或新增内联 style 标签。捕获 pointerId，用起始宽度加 startX-clientX 得到新宽度；pointerup 保存，pointercancel/blur/关闭取消拖动态。设置/移除 dragging class，恢复文本选择和内容指针响应。
- [ ] 绑定键盘、双击、resize，更新 separator aria-valuemin/max/now；Home/双击清除存储并刷新默认值；destroy 移除监听并释放捕获。
- [ ] 模拟 DOM 与 storage 验证：拖动方向/上下限、指针取消、异常存储、无效数值、重置、resize 不覆盖偏好、destroy 后无响应。测试通过后本地提交模块和测试。

## Task 2: 接入面板和静态资源

**Files:** 修改 `web/index.html`、`web/style.css`、`web/app.js`、`static_assets.py`、`lan_web.py`、`tests/test_static_assets.py`（以上 Python 文件位于 `lan_codex_share/`）。

- [ ] 在 aside 内添加绝对定位分隔条，不占 Grid 新行：

```html
<div id="preview-resize" class="preview-resize" role="separator" tabindex="0"
     aria-orientation="vertical" aria-label="调整预览宽度"
     aria-controls="file-preview" title="左右拖动调整宽度；双击恢复默认"></div>
```

- [ ] CSS 使 file-preview 成为定位容器，拖动条位于左边界内侧、宽 10px、全高，cursor:col-resize 与 touch-action:none；hover/focus-visible 高亮。dragging 时禁用选择和 PDF/object 指针响应。窄屏隐藏。
- [ ] 桌面 Grid 第三栏改为 `var(--preview-width, minmax(420px,min(45vw,760px)))`；浮层 width 读取变量并限制视口；移动布局保持100%。恢复默认由控制器刷新处理。
- [ ] app.js 创建一个控制器；打开/关闭面板时刷新/取消。公告复用面板的打开入口也纳入 refresh，不改变文件解析流程。必要时以观察 preview-open class 的方式统一生命周期，避免文档测试夹具引入无关初始化依赖。
- [ ] index.html 在 app.js 前加载新脚本；StaticAssets 名单和旧直接静态路由加入 preview-resize.js，更新资源数断言（9→10）。运行全部 JS 测试与 `pytest tests/test_static_assets.py tests/test_lan_web.py -q`。
- [ ] 本地提交集成文件，仅显式暂存相关文件。

## Task 3: 浏览器验证与说明

**Files:** 更新 `README.md` 的预览说明；复用 `tests/fixtures/archive_preview_page.py`，截图放入忽略的 `output/playwright/`。

- [ ] 用独立模拟会话服务器测试，不接入真实 Codex。宽屏打开 ZIP/XLSX，拖动前后记录面板宽度和文件请求数量；确认宽度变化而请求数不变，预览内容与滚动位置保留。
- [ ] 重新加载验证偏好，双击/Home 验证恢复默认；拖动后关闭预览确认聊天区恢复。测试 1000px 浮层与 375px 全屏，无页面横向溢出；检查控制台无新增 CSP 违规。
- [ ] README 补充拖动、双击、键盘和本机记忆说明。
- [ ] 执行所有 JS 测试、Python 回归及 `git diff --check`，记录真实数量及未验证项。停止自己创建的测试服务和浏览器，不操作用户服务。
- [ ] 提交文档和验证记录，留在当前分支，不推送/发布。

## 自检

三个任务覆盖尺寸规则、生命周期、CSP、响应式、资源指纹和浏览器验收；控制器接口统一，未引入依赖或后端配置。键盘替代交互避免功能仅支持鼠标拖动。
