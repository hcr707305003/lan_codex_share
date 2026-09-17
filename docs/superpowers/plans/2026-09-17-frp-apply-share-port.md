# FRP Apply Share Port Implementation Plan

> **For agentic workers:** Use executing-plans inline; retain current branch and working directory.

**Goal:** FRP localPort 表单支持一键应用已保存的 Share 端口。

**Architecture:** 在 ConfigPage 的本地端口输入旁添加按钮；回调使用 load_lan_config 校验并读取当前端口，再复用 field_changed 更新草稿。

**Tech Stack:** Python、PySide6、pytest。

**Spec:** docs/superpowers/specs/2026-09-17-frp-apply-share-port-design.md

## Global Constraints

- 只改当前 TCP 代理 localPort，不改其他字段。
- 保存前不写文件，不操作服务，不提交、打包或发布。

### Task 1: 按钮与验证

- [x] 新增 tests/test_frp_apply_share_port.py：实际点击按钮，验证读取当前端口、同值、无效源配置、选择代理和保存后字段保留。
- [x] 运行测试确认按钮不存在导致失败。
- [x] 修改 desktop/config_page.py：本地端口行使用 QHBoxLayout 放置输入与按钮；回调读取 load_lan_config(self.lan_path).port，读取失败只提示，成功复用 field_changed。
- [x] 运行定向与全量测试，并检查四主题布局。
- [x] 更新 README.md 和 DESKTOP.md 的 FRP 配置说明，git diff --check。
- [x] 用户追加：Share、FRP、Cloudflare 表单全部字段添加静态行下说明与辅助阅读描述；测试不包含实际密钥、不制造脏状态、高级模式隐藏说明，更新文档与截图。

验证结果：完整 pytest 733 项通过（57.83 秒）；FRP 与 Cloudflare 四主题、两种尺寸检查通过，已查看实际渲染截图并更新 README 演示图。未提交、打包、发布或操作运行服务。

### 回归修复：字段说明被遮挡

- [x] 复现 Share 窄控件导致说明区域缩窄：1050px 表单下 Session 说明仅 260px，而其他字段说明为 819px。
- [x] 将字段与说明封装为可横向扩展的 QWidget，显式保留文字换行的 height-for-width 策略，使说明完整占用字段列并按内容撑高。
- [x] 增加三类表单的连续缩放回归测试，检查说明宽度、高度及父容器边界；确认没有改变配置草稿。
- [x] 使用临时演示配置离屏渲染 Share：四主题、900/1280px 窗口、100%/150% 缩放，实际查看权限和任务提示说明，无遮挡。

回归验证：完整 pytest 736 项通过（65.34 秒）；补充边界断言后字段说明专项 6 项通过。仅修改源码及测试，未提交、打包、发布或操作运行服务。

### 二次回归：切换 Session 后预览目录区域塌陷

- [x] 用包含四个预览目录的配置复现：从指定 Session 切换到共享全部后，目录编辑器从正常高度被压到 58px，列表、按钮和说明重叠。上一轮只检查静态尺寸和说明标签，未覆盖这个操作顺序。
- [x] 将 QFormLayout 放入滚动内容的纵向布局并保留底部弹性空间，让动态字段显隐后整个表单按内容高度重新分配，避免压缩复杂字段；不使用固定高度或定时器补丁。
- [x] 回归测试覆盖宽/窄窗口、三种 Session 模式反复切换、滚动到底部、实际点击目录添加/移除按钮（文件选择器使用临时目录）、高级编辑往返；同时检查内部控件和相邻表单行不重叠。
- [x] 使用四个示例目录重新渲染四种主题、900/1280px 窗口、100%/150% 缩放，查看预览目录完整区域；保留临时演示截图供本地核对。

二次回归验证：完整 pytest 738 项通过（64.95 秒）；未修改真实配置、未操作用户服务、未打包发布。
