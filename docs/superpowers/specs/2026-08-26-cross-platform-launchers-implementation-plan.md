# 跨平台启动脚本实施计划

## 目标

在不改变现有 Windows `.cmd` 行为的前提下，增加 macOS、Linux、Git Bash/WSL 可使用的 POSIX Shell 启动入口，并让 Python 服务的单实例锁可以在 Windows 与 POSIX 系统运行。

## 任务 1：跨平台单实例锁

修改 `lan_codex_share/lan_main.py`：

1. 移除模块顶层对 `msvcrt` 的无条件导入。
2. 增加按平台加载锁模块的内部辅助函数。
3. Windows 使用 `msvcrt.LK_NBLCK` 与 `msvcrt.LK_UNLCK`。
4. macOS/Linux 使用 `fcntl.LOCK_EX | LOCK_NB` 与 `LOCK_UN`。
5. 保持 `SingleInstanceLock` 的公开接口、锁文件路径和错误信息不变。
6. 将启动成功提示中的 CLI 入口改为同时列出 `.cmd` 和 `.sh`，将防火墙提示改为跨平台措辞。

修改 `lan_codex_share/codex_client.py`，将锁冲突提示里的 Windows 专属脚本名改为同时覆盖两个平台入口。

## 任务 2：POSIX Shell 入口

新增 `start_lan_codex_share.sh`：

1. 使用 `/bin/sh` 和 POSIX 语法。
2. 根据脚本自身位置解析项目根目录并切换目录。
3. 依次探测 `.venv/bin/python` 与 `.venv/Scripts/python.exe`。
4. 检查 `lan_config.toml`。
5. 使用 `exec` 启动 `lan_codex_share.lan_main`，返回原进程退出码。

新增 `open_lan_codex_cli.sh`，采用相同环境检查，并通过 `"$@"` 原样转发 Session 等参数给 `lan_codex_share.lan_cli`。

使用 Git 可执行位标记两个脚本。

## 任务 3：自动化测试

修改 `tests/test_lan_main.py`：

1. 保留真实平台上的重复加锁测试。
2. 使用可控的假锁模块验证 Windows 与 POSIX 分支选择的常量和调用方式。
3. 验证退出上下文会执行解锁。

新增或扩展启动脚本测试，读取脚本文本并验证：

- 使用 POSIX `sh`。
- 从脚本目录运行。
- 支持两种虚拟环境路径。
- CLI 参数使用 `"$@"` 转发。
- 不包含个人绝对路径。

## 任务 4：README

更新 `README.md`：

1. 将项目适用范围从 Windows 扩展到 Windows、macOS 和 Linux。
2. 分开提供 Windows PowerShell 与 macOS/Linux 安装命令。
3. 说明 Windows `.cmd` 和 POSIX `.sh` 的启动方法。
4. 说明 Git Bash 可探测 Windows 虚拟环境，WSL 需要在 WSL 内创建独立虚拟环境并安装 Codex CLI。
5. 保留局域网安全、配置文件和 Session 使用说明。

## 任务 5：验证与交付

执行：

```text
python -m pytest -q
sh -n start_lan_codex_share.sh
sh -n open_lan_codex_cli.sh
git diff --check
```

确认 `.gitignore` 继续排除日志、运行数据、上传图片、虚拟环境和本机配置。完成后提交功能改动并推送 `origin/main`。
