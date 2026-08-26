# 可选密码认证实施计划

## 成功标准

- `password = ""` 时所有现有行为保持不变。
- 非空密码时，未认证用户不能读取或修改任何 Session、图片或工作区文件。
- 正确密码签发仅限当前浏览器会话的 HttpOnly Cookie，刷新和切换 Session 后保持登录。
- 登录前不建立 EventSource，运行期认证失效会回到登录界面。
- 密码和认证 token 不进入 URL、响应正文或日志。
- 全部自动化验证通过，不生成发行包。

## 任务一：配置链路

修改 `lan_codex_share/lan_config.py`、`lan_codex_share/lan_main.py`、`lan_config.example.toml` 和 `README.md`：

1. 为 `LanConfig` 增加默认空字符串密码。
2. 解析密码时保留字符串原值，只允许字符串类型。
3. 将密码传给 `LanWebApplication`，禁止记录密码。
4. 示例配置使用空值，README 说明启用方法和局域网 HTTP 的安全边界。
5. 增加默认值、非空值、空格保留和错误类型测试。

## 任务二：服务端认证状态

修改 `lan_codex_share/lan_web.py`：

1. Web 应用保存配置密码、随机认证 token 和按 IP 的失败时间窗口。
2. 使用 `SimpleCookie` 解析 Cookie，使用 `hmac.compare_digest` 比较密码和 token。
3. 增加 `GET /api/auth/status` 和 `POST /api/auth/login`。
4. 登录成功设置 `HttpOnly; SameSite=Strict; Path=/` 的会话 Cookie。
5. 登录失败按 IP 记录；60 秒内达到 5 次后返回 `429`，成功后清除失败记录。
6. 密码启用时，在所有业务 GET/POST 路由之前校验 Cookie。
7. 未认证统一返回 `401`，不泄露密码或 token。

## 任务三：登录界面和启动流程

修改 `lan_codex_share/web/index.html`、`style.css` 和 `app.js`：

1. 增加带明确 label 的密码表单、状态提示和提交按钮。
2. 输入框允许粘贴并使用 `autocomplete="current-password"`，保留可见键盘焦点。
3. 登录层适配桌面和小屏幕，不改变现有 Codex 风格。
4. 页面先检查认证状态；只有认证成功后才加载快照并创建 EventSource。
5. 登录期间提供处理反馈；错误密码和限流显示明确但不泄密的提示。
6. 任一数据请求返回 `401` 时停止实时连接并重新显示登录层。

## 任务四：服务端回归测试

扩展 `tests/test_lan_web.py`：

1. 验证空密码兼容行为。
2. 验证认证状态、错误密码、正确密码和 Cookie 属性。
3. 验证伪造 Cookie 被拒绝，有效 Cookie 可访问快照、SSE、图片、文件和写接口。
4. 验证失败次数限制、时间窗口过期和成功登录清除失败记录。
5. 验证页面静态资源仍可在未登录时读取。

## 任务五：前端静态验证

扩展现有页面资源断言，并验证：

1. 登录表单具有 label、autocomplete、状态区域和正确的按钮语义。
2. JavaScript 不在认证前创建 EventSource。
3. JavaScript 处理 `401` 和 `429`，并在认证后只启动一条实时连接。
4. CSS 包含登录层的自适应、焦点与处理中状态。

## 任务六：完整验证与提交

1. 运行目标 pytest。
2. 运行完整 pytest。
3. 使用 Node 检查 JavaScript 语法。
4. 运行 Python 编译检查和 `git diff --check`。
5. 检查密码、token、本机配置与日志未进入提交。
6. 提交并推送源码，等待 CI 成功；不更新版本号、不打包、不创建 Release。
