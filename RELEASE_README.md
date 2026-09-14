# LAN Codex Share

此版本包包含一个原生可执行程序，不需要安装 Python。目标机器仍需安装并登录 Codex CLI，确认 `codex --version` 可用。

## 使用

1. 将 `lan_config.example.toml` 复制为 `lan_config.toml`。
2. 修改 `workspace`、`session_ids`、权限、端口和可选密码。
3. 启动共享服务：

`session_ids = []` 会共享本机全部未归档主 Session，并按项目分组；填入 ID 数组时只共享指定 Session；删除该配置项时使用单会话自动模式。

`password = ""` 表示不启用登录；设置非空密码后，浏览器必须先登录才能访问 Session、消息、图片和文件。登录状态保留到浏览器会话结束或共享程序重启。

```text
lan_codex_share --config=lan_config.toml
```

Windows 使用 `lan_codex_share.exe`；macOS/Linux 使用 `./lan_codex_share`。未指定 `--config` 时，程序读取可执行文件同目录的 `lan_config.toml`。

打开共享 Session 的本机 CLI：

```text
lan_codex_share cli --config=lan_config.toml
lan_codex_share cli --config=lan_config.toml --session 01example
```

Windows 程序名为 `lan_codex_share.exe`。macOS/Linux 首次解压后如缺少执行权限，请运行 `chmod +x lan_codex_share`。

此版本未进行 Windows 代码签名或 macOS 公证。运行前可使用 Release 中的 `SHA256SUMS.txt` 核对下载文件。即使启用了密码，默认局域网 HTTP 连接也不会加密传输内容和密码；不要直接映射 HTTP 端口到公网。

## 可选公网入口

配置 `public_origin = "https://codex.example.com"`，让同机运行的 Cloudflare Tunnel 将该域名回源到 `http://localhost:你的Web端口`，保留原始 Host。此模式只接受本机回环代理连接，支持公网 HTTPS 登录、消息发送和事件流，不需要 Cloudflare Access 登录。原局域网 HTTP 入口保持不变。

强烈建议设置项目 `password`。密码留空仍会完全免登录，并非只读：任何访问者均可查看共享会话、读取授权文件、发送任务，并按配置权限操作本机。程序启动时会警告。修改密码后需重启，旧登录状态随即失效。同一 Tunnel 的访问者共享登录失败限流额度。

## 动态反代

直接访问 `https://你的域名/proxy/localhost:1122/` 或 `http://你的内网地址:Web端口/proxy/192.168.1.20:3301/` 即可代理其他 HTTP 服务，不用逐个配置。`localhost` 指共享程序所在电脑；保留现有 Tunnel 回源映射，不需要新子域名。支持常见请求方法、上传下载、SSE 和 WebSocket；不支持任意域名、公网目标、HTTPS-only 回源或任意 TCP 协议。共享端口和 Codex App Server 端口禁止代理。

前后端分端口时也能自动转发：例如 `/proxy/localhost:3301/#/login` 中请求 `http://localhost:13333/api/users`，会改为同域名 `/proxy/localhost:13333/api/users`。支持 fetch/Request、XHR/Axios（XHR 适配器）、WebSocket、EventSource 和常见资源链接/重定向；无需额外服务列表。浏览器侧只映射本机/内网 HTTP/WS 地址，不改写公网地址；严格 CSP、Worker 等仍可能需要应用侧适配。

JSON 中指向当前后端同一主机和端口的完整 HTTP/HTTPS 资源 URL 会转换成分享域名下的反代地址，例如接口根据公网协议头生成的内网二维码图片地址。该兼容处理不等于支持任意 HTTPS 回源；保留查询参数、普通文字和业务数字。只处理不超过 2 MiB 的未压缩 HTML/CSS/JSON；部分响应不改写。

反代入口沿用项目密码。密码为空时所有访问者均可访问允许范围内的本机/内网服务，且目标服务操作不受 Codex `permission_mode` 约束。同域名反代不是沙箱，只应接入可信服务。子路径适配为尽力兼容，严格 CSP 或写死路径的应用仍可能需要自身调整。HTTP 超时 30 秒，上传上限 128 MiB，WebSocket 单方向空闲超时 30 分钟。

## 升级与排查

v0.1.7 优化长会话：首屏只加载最近 20 轮问答，上滑接近顶部自动加载更早 20 轮，并保持阅读位置。工具过程展开后分页读取，流式回复只更新变化的消息。历史不会删除，刷新或切换 Session 不影响后台任务；“回到最近 20 轮”可释放旧内容，历史加载失败时显示重试按钮。共享服务首次恢复 Session 仍需读取完整记录，单条极长回复仍有渲染成本。

保留 `lan_config.toml` 和 `runtime/`，停止旧程序后替换可执行文件，再启动并刷新浏览器；不要用示例配置覆盖个人配置。公网 502 时先检查同机共享程序和 Tunnel 回源；页面白屏时检查必需 JS/CSS 请求。v0.1.6 增大连接等待队列以缓解资源加载突发连接重置，并不保证解决所有网络 502。

按一次 Ctrl+C 后等待退出清理，避免连续中断；重复 Ctrl+C 的退出体验不在本版本修复范围。程序不会管理被代理服务。更多配置与限制见 [项目 README](https://github.com/hcr707305003/lan_codex_share#readme)。
