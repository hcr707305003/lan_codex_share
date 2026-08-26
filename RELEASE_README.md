# LAN Codex Share

此版本包包含一个原生可执行程序，不需要安装 Python。目标机器仍需安装并登录 Codex CLI，确认 `codex --version` 可用。

## 使用

1. 将 `lan_config.example.toml` 复制为 `lan_config.toml`。
2. 修改 `workspace`、`session_ids`、权限和端口。
3. 启动共享服务：

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

此版本未进行 Windows 代码签名或 macOS 公证。运行前可使用 Release 中的 `SHA256SUMS.txt` 核对下载文件。局域网入口没有账号密码，请仅在可信网络使用，不要映射到公网。
