# LAN Codex Share

此版本包保留 Share/CLI 原生程序；包含桌面组件的包还提供 `lan_codex_desktop.exe`（Windows）、`LAN Codex Share.app`（macOS）或 `lan_codex_desktop`（Linux）。不需要安装 Python，但目标机器仍需安装并登录 Codex CLI，确认 `codex --version` 可用。

## 桌面启动

双击桌面程序，或使用 `lan_codex_desktop --config=./lan_config.toml`。默认配置位于发行目录（macOS 在 `.app` 外侧）。窗口启动不会自动启动服务或连接隧道。

服务总览独立控制 Share、frpc 与 Cloudflare；配置管理保存文件但不自动重启。frpc 的 token 填在 `frpc.toml` 的 `auth.token`，Cloudflare 可使用本地 YAML 或单独的 token 文件。缺少 frpc 时，组件管理提供官方校验下载、选择已有程序和官方下载页。

配置、token 文件和日志只留本地，不要分享原始配置截图。日志有脱敏处理，但导出前仍须检查业务内容。关闭窗口时会询问是否停止本窗口启动的服务；不会接管或停止外部服务。

## 使用

1. 将 `lan_config.example.toml` 复制为 `lan_config.toml`。
2. 修改 `workspace`、`session_ids`、权限、端口和可选密码。
3. 启动共享服务：

`session_ids = []` 会共享本机全部未归档主 Session，并按项目分组；填入 ID 数组时只共享指定 Session；删除该配置项时使用单会话自动模式。

`password = ""` 表示不启用登录；设置非空密码后，浏览器必须先登录才能访问 Session、消息、图片和文件。登录后固定有效 30 天，期间重启程序或关闭浏览器无需再次输入密码。修改密码并重启后旧登录失效；清除 Cookie、无痕窗口关闭或切换访问域名仍需登录。

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

配置 `cloudflare_origin = "https://codex.example.com"`，让同机运行的 Cloudflare Tunnel 将该域名回源到 `http://localhost:你的Web端口`，保留原始 Host。此模式只接受本机回环代理连接，支持公网 HTTPS 登录、消息发送和事件流，不需要 Cloudflare Access 登录。原局域网 HTTP 入口保持不变。

强烈建议设置项目 `password`。密码留空仍会完全免登录，并非只读：任何访问者均可查看共享会话、读取授权文件、发送任务，并按配置权限操作本机。程序启动时会警告。修改密码后需重启，旧登录状态随即失效。同一 Tunnel 的访问者共享登录失败限流额度。

## 动态反代

### 使用已有 frps 的 IP＋端口入口

支持把一个 frp TCP 业务端口转发到本机共享端口：例如 `公网 IP:20000 → 同机 frpc → 127.0.0.1:9000`。共享配置设置 `port = 9000`、`frp_origin = "http://192.0.2.10:20000"` 和非空项目密码；示例 IP 必须替换为实际服务器地址。frpc 中 `localPort = 9000`、`remotePort = 20000`，控制连接端口按 frps 配置填写（例如 7000），与业务端口不同。

随后访问同一入口的 `/` 使用 Codex，访问 `/proxy/localhost:13333/`、`/proxy/localhost:3301/` 使用其他服务，无需新增 frp 映射。frpc 必须在共享程序同机运行并回源回环地址，保留原始 Host、不启用 PROXY protocol。frpc 需要自行安装和手动启动，当前版本包不内置其二进制。

HTTP 公网模式要求非空密码，但浏览器到服务器的流量仍为明文；frp TLS 只保护 frpc/frps 之间的链路。Cookie 不按公网端口隔离，同一 IP 不应承载不可信服务。敏感使用请配置专属 HTTPS 域名。完整示例和启动脚本见 [项目 frp 文档](https://github.com/hcr707305003/lan_codex_share#frp-单端口公网访问)。

`cloudflare_origin` 与 `frp_origin` 可都留空、只设置一个或同时填写；同时启用时两个穿透客户端均回源同一 Web 端口，共用 Session、队列和项目密码，浏览器按域名/IP 分别保存登录。只声明配置不会自动启动穿透客户端。旧 `public_origin` 可单独使用，改用新字段时必须删除旧字段（包括空值），混用会报错。更改入口配置后手动重启，原局域网访问方式不变。

### 多服务路径

直接访问 `https://你的域名/proxy/localhost:1122/` 或 `http://你的内网地址:Web端口/proxy/192.168.1.20:3301/` 即可代理其他 HTTP 服务，不用逐个配置。`localhost` 指共享程序所在电脑；保留现有 Tunnel 回源映射，不需要新子域名。支持常见请求方法、上传下载、SSE 和 WebSocket；不支持任意域名、公网目标、HTTPS-only 回源或任意 TCP 协议。共享端口和 Codex App Server 端口禁止代理。

前后端分端口时也能自动转发：例如 `/proxy/localhost:3301/#/login` 中请求 `http://localhost:13333/api/users`，会改为同域名 `/proxy/localhost:13333/api/users`。支持 fetch/Request、XHR/Axios（XHR 适配器）、WebSocket、EventSource 和常见资源链接/重定向；无需额外服务列表。浏览器侧只映射本机/内网 HTTP/WS 地址，不改写公网地址；严格 CSP、Worker 等仍可能需要应用侧适配。

JSON 中指向当前后端同一主机和端口的完整 HTTP/HTTPS 资源 URL 会转换成分享域名下的反代地址，例如接口根据公网协议头生成的内网二维码图片地址。该兼容处理不等于支持任意 HTTPS 回源；保留查询参数、普通文字和业务数字。只处理不超过 2 MiB 的未压缩 HTML/CSS/JSON；部分响应不改写。

反代入口沿用项目密码。密码为空时所有访问者均可访问允许范围内的本机/内网服务，且目标服务操作不受 Codex `permission_mode` 约束。同域名反代不是沙箱，只应接入可信服务。子路径适配为尽力兼容，严格 CSP 或写死路径的应用仍可能需要自身调整。HTTP 超时 30 秒，上传上限 128 MiB，WebSocket 单方向空闲超时 30 分钟。

## 升级与排查

v0.1.8 新增内容指纹静态缓存和实时增量推送：未变化的 JS/CSS 可复用缓存，代码更新会引用新地址；正常实时回复不再逐次额外拉取快照，断线重连自动补齐。首页及会话、图片、文件和代理内容仍不公共缓存；不要为整个域名启用“缓存所有内容”。已打开的页面需手动刷新才使用新版，不会强制打断任务，优化不消除 Tunnel 链路延迟。

从旧版升级到 v0.1.8 后需重新登录一次。此后请保留配置旁的 `runtime/lan/auth.json`，否则会要求重新登录；该文件含敏感签名密钥，不要分享或提交。需要撤销全部登录时，停止共享程序、删除此文件再启动；密码修改后重启也会撤销旧登录。凭证到期由服务器校验，浏览器中不保存密码明文。

v0.1.7 优化长会话：首屏只加载最近 20 轮问答，上滑接近顶部自动加载更早 20 轮，并保持阅读位置。工具过程展开后分页读取，流式回复只更新变化的消息。历史不会删除，刷新或切换 Session 不影响后台任务；“回到最近 20 轮”可释放旧内容，历史加载失败时显示重试按钮。共享服务首次恢复 Session 仍需读取完整记录，单条极长回复仍有渲染成本。

保留 `lan_config.toml` 和 `runtime/`，停止旧程序后替换可执行文件，再启动并刷新浏览器；不要用示例配置覆盖个人配置。公网 502 时先检查同机共享程序和 Tunnel 回源；页面白屏时检查必需 JS/CSS 请求。v0.1.6 增大连接等待队列以缓解资源加载突发连接重置，并不保证解决所有网络 502。

按一次 Ctrl+C 后等待退出清理，避免连续中断；重复 Ctrl+C 的退出体验不在本版本修复范围。程序不会管理被代理服务。更多配置与限制见 [项目 README](https://github.com/hcr707305003/lan_codex_share#readme)。
