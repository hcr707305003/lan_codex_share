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

此版本未进行 Windows 代码签名或 macOS 公证。运行前可使用 Release 中的 `SHA256SUMS.txt` 核对下载文件。即使启用了密码，默认局域网 HTTP 连接也不会加密传输内容和密码；请仅在可信网络使用，不要映射到公网。
