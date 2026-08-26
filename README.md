# 局域网共享 Codex 会话

在 Windows、macOS 或 Linux 本机托管一个或多个固定的 Codex Session，并通过浏览器分享给同一局域网内的同事。所有访问者可以切换共享会话，查看各自的聊天历史和实时任务进度，发送文字和 PNG/JPEG/WebP 图片，并在配置权限内操作本地工作区。

## 前置条件

- Python 3.11 或更高版本；Windows 通常使用 `python`，macOS/Linux 通常使用 `python3`。
- Codex CLI 已安装并登录，`codex --version` 可用。

## 首次安装

Windows PowerShell：

```powershell
git clone <repository-url> lan-codex-share
cd lan-codex-share
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item lan_config.example.toml lan_config.toml
```

macOS/Linux：

```sh
git clone <repository-url> lan-codex-share
cd lan-codex-share
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp lan_config.example.toml lan_config.toml
chmod +x start_lan_codex_share.sh open_lan_codex_cli.sh
```

编辑 `lan_config.toml`，至少确认工作区、共享会话、权限模式、端口和文件预览目录。

## 运行

Windows 可以双击 `start_lan_codex_share.cmd`；macOS/Linux 在终端运行：

```sh
./start_lan_codex_share.sh
```

启动窗口会显示类似 `http://192.168.1.20:8765/` 的分享地址和全部 Session ID。网页顶部可以切换 Session；选中的 ID 会写入地址栏，因此复制当前网址就能让同事直接打开同一会话。不同浏览器可以同时停留在不同 Session，互不抢占选择状态。其他设备无法连接时，请在当前系统防火墙中允许 Python/Codex 访问局域网；脚本不会自动修改防火墙。

网页端采用 Codex 风格的任务界面，支持 Enter 发送、Shift+Enter 换行、拖拽图片和 Ctrl+V 粘贴图片。它直接投影真实 Session：回复、可读的思考摘要、命令输出、工具调用和文件修改都会实时流式显示；执行中自动展开过程，完成后默认折叠，可随时手动重开。隐藏的原始推理链不会对外展示。

回复中的本地文件 Markdown 链接可以点击，并在会话右侧预览。Markdown 会格式化显示，常见源码和文本提供行号；`文件路径:行号:列号` 会自动定位并高亮。图片和 PDF 也可内嵌查看。只允许读取 `workspace` 和 `preview_roots` 显式授权的目录。

共享服务和本机 CLI 启动器都连接 `127.0.0.1:app_server_port` 上的同一个 App Server，因此可以同时查看和操作 Session，不会争抢会话文件锁。若该端口已经由兼容的 Codex App Server 占用，启动器会直接复用。Windows 可以双击 `open_lan_codex_cli.cmd`；macOS/Linux 运行 `./open_lan_codex_cli.sh`。多会话配置默认打开第一项，也可以指定 Session：

```sh
./open_lan_codex_cli.sh --session <Session ID>
```

Windows 终端对应使用 `open_lan_codex_cli.cmd --session <Session ID>`。不要另起一个不同的 App Server 同时写入同一 Session。

Windows Git Bash 可以直接运行 `.sh`，脚本会自动识别 `.venv/Scripts/python.exe`。WSL 属于独立的 Linux 环境，应在 WSL 内创建 `.venv`、安装依赖并登录 Codex CLI，不要直接复用 Windows 虚拟环境。

配置文件为 `lan_config.toml`：

```toml
workspace = "../workspace"
session_ids = [
  "01xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "01yyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
]
permission_mode = "danger-full-access"
host = "0.0.0.0"
port = 8765
app_server_port = 4500
preview_roots = [
  "../another-project",
]
```

相对路径以 `lan_config.toml` 所在目录为基准。`lan_config.toml` 是本机配置，已被 Git 忽略；仓库只提交不含个人路径的 `lan_config.example.toml`。

- `session_ids = []`：单会话自动模式。复用 `runtime/lan/state.json` 保存的会话；没有记录时自动创建。
- `session_ids = ["Session A", "Session B"]`：固定共享这些会话。每个会话拥有独立历史投影、处理状态、模型设置和等待队列，并可同时执行任务；任一会话恢复失败时启动会直接报错，不会自动创建替代会话。
- 旧版 `session_id = "..."` 仍可读取，便于升级，但不能与 `session_ids` 同时配置。
- `permission_mode = "read-only"`：只读访问。
- `permission_mode = "workspace-write"`：允许修改工作区。
- `permission_mode = "danger-full-access"`：完全访问本机文件系统。

网页目前没有交互式审批弹窗，因此审批策略固定为 `never`；实际访问范围由 `permission_mode` 限制。本机 CLI 会连接所选 Session，并采用相同权限模式。

局域网入口没有账号或密码。任何能访问地址的局域网设备都可以读取共享聊天记录、发送任务、上传图片、取消当前任务，并在配置的权限范围内操作本机文件。只应在可信局域网内使用，不要进行公网端口映射。
