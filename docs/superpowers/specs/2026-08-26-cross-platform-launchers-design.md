# 跨平台启动脚本设计

## 目标

在保留现有 Windows `.cmd` 启动方式的同时，为 macOS、Linux 以及 Windows 的 Git Bash/WSL 提供对应 Shell 启动脚本，并修复应用当前对 Windows 专用文件锁的依赖，使项目能够在 Codex CLI 支持的平台上运行。

## 范围

本次新增两个入口：

- `start_lan_codex_share.sh`：启动局域网 Codex 会话共享服务。
- `open_lan_codex_cli.sh`：连接共享 App Server，并打开指定或默认 Session 的本机 Codex CLI。

现有 `start_lan_codex_share.cmd` 和 `open_lan_codex_cli.cmd` 保持可用。本次不引入安装器、Python 包发布流程、服务守护进程、防火墙自动配置或 PHP 服务管理。

## 启动脚本行为

两个 Shell 脚本使用 POSIX `sh` 语法，不依赖 Bash 专属功能。脚本根据自身路径切换到项目根目录，避免调用者当前工作目录影响配置和运行数据位置。

脚本固定使用项目虚拟环境，不回退到系统 Python，以确保依赖版本明确。优先探测 POSIX 虚拟环境的 `.venv/bin/python`，随后探测 Windows Git Bash 可执行的 `.venv/Scripts/python.exe`。若两者都不存在或 `lan_config.toml` 不存在，脚本输出可直接复制执行的安装或配置提示，并使用非零状态码退出。

`open_lan_codex_cli.sh` 将调用参数原样转发给 `lan_codex_share.lan_cli`，因此支持：

```sh
./open_lan_codex_cli.sh --session <SESSION_ID>
```

Shell 脚本不暂停等待按键；底层 Python 进程的退出码会原样返回，便于终端、CI 或其他脚本判断结果。

## Python 平台兼容

`lan_main.py` 的单实例锁保留统一的 `SingleInstanceLock` 接口，并在内部按平台选择实现：

- Windows：继续使用 `msvcrt.locking`。
- macOS/Linux：使用 `fcntl.flock` 的非阻塞排他锁。

两种实现都锁定 `runtime/lan/server.lock`，第二个共享服务进程无法取得锁时继续返回“服务已经在运行”的明确错误。退出上下文时释放锁并关闭文件；异常路径同样不得泄漏文件句柄。

Codex 命令查找继续兼容 `codex.cmd`、`codex.exe` 和 `codex`。其他路径、配置、Web 服务和 Session 行为保持不变。

## 文档

README 将项目描述调整为跨平台，并分别说明：

- Windows PowerShell 创建虚拟环境、安装依赖和复制配置。
- macOS/Linux 使用 `python3`、`.venv/bin/python` 和 `cp` 完成安装。
- Windows 双击 `.cmd` 或在终端调用。
- macOS/Linux 首次执行 `chmod +x *.sh`，随后运行对应 `.sh`。
- Windows Git Bash 可以使用 `.sh`；WSL 应使用 WSL 内安装的 Python 和 Codex CLI，不能直接假设复用 Windows 虚拟环境。

## 错误处理

- 缺少可用的 `.venv/bin/python` 或 `.venv/Scripts/python.exe`：退出码 `1`，提示创建虚拟环境和安装依赖。
- 缺少 `lan_config.toml`：退出码 `2`，提示复制示例配置。
- Python 服务或 CLI 启动失败：返回底层进程退出码。
- 单实例锁冲突：沿用应用现有启动失败流程，不启动第二个服务。

## 验证

- 为 Windows 和 POSIX 锁分支补充单元测试或可注入的行为测试，验证加锁、冲突和释放。
- 运行完整 `pytest` 回归测试。
- 使用 `sh -n start_lan_codex_share.sh` 和 `sh -n open_lan_codex_cli.sh` 做 POSIX Shell 语法检查。
- 检查脚本可执行位已提交到 Git。
- 检查 README 示例不包含个人路径、Session ID 或本机配置。

## 验收标准

- Windows 原有 `.cmd` 启动方式不变。
- macOS/Linux 可通过 `.sh` 启动共享服务和本机 CLI。
- Git Bash/WSL 的使用边界在 README 中清晰说明。
- macOS/Linux 导入并运行 `lan_main.py` 时不再因缺少 `msvcrt` 失败。
- 日志、上传文件、虚拟环境和 `lan_config.toml` 仍被 Git 忽略。
