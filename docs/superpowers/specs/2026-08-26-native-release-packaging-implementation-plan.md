# 原生版本包实施计划

## 任务 1：统一启动入口与路径模型

新增 `lan_codex_share/launcher.py` 和 `lan_codex_share/__main__.py`：

1. 单一程序默认进入 Share 模式。
2. 支持显式 `share` 和 `cli` 模式。
3. 支持 `--config=value`、`--config value`、`--session`、`--version` 和分模式帮助。
4. 冻结程序默认从 `sys.executable` 同目录读取配置；源码模式默认从仓库根目录读取配置。
5. 显式相对配置按调用者当前目录解析。

重构 `lan_main.py` 与 `lan_cli.py`：

1. 提取接收绝对配置路径的运行函数。
2. 将 `runtime/lan` 从当前目录迁移为配置文件目录。
3. 保留两个模块原有命令行入口和 `.cmd/.sh` 兼容性。

## 任务 2：冻结资源与 PyInstaller

新增根入口脚本和 PyInstaller Spec：

1. 入口只调用统一 Launcher。
2. 使用 `onefile` 控制台程序。
3. 收集 `lan_codex_share/web` 静态资源。
4. 确保 Windows 输出 `.exe`，POSIX 输出无扩展名可执行文件。
5. 添加本地构建与打包脚本，输出单个平台 ZIP。

发布包固定包含主程序、`lan_config.example.toml` 和发布版 README，不包含本机配置或运行数据。

## 任务 3：GitHub Actions 五平台构建

新增 `.github/workflows/release.yml`：

1. 普通分支与 Pull Request 只运行测试和打包配置检查。
2. `v*` Tag 在以下原生 Runner 构建：
   - `windows-2025` / Windows x64
   - `ubuntu-24.04` / Linux x64
   - `ubuntu-24.04-arm` / Linux ARM64
   - `macos-15-intel` / macOS x64
   - `macos-15` / macOS ARM64
3. 每个平台运行 PyInstaller、`--version`/`--help` 烟雾测试和 ZIP 内容检查。
4. 汇总 ZIP，生成 `SHA256SUMS.txt`。
5. 使用 `GITHUB_TOKEN` 创建对应 Tag 的 GitHub Release。

## 任务 4：测试与文档

新增 Launcher 与发布脚本测试，覆盖：

- 默认配置路径与显式相对/绝对路径。
- 默认 Share、显式 Share、CLI 模式。
- 两种 `--config` 写法和 Session 转发。
- 配置目录决定运行目录。
- 源码与模拟冻结环境的程序目录。
- Spec 包含 Web 资源。
- ZIP 文件名、内容和个人数据排除规则。

更新 README，增加二进制包使用、五个平台、未知发布者提示和 SHA-256 验证说明。

## 任务 5：本地与远程发布验证

本地执行：

```text
python -m pytest -q
python -m PyInstaller --clean --noconfirm lan_codex_share.spec
dist/lan_codex_share --version
dist/lan_codex_share --help
git diff --check
```

Windows 使用 `.exe` 后缀。验证本地 Windows ZIP 内容后提交并推送 `main`，创建并推送 `v0.1.0` Tag。持续检查 GitHub Actions，直到五个平台产物和 Release 全部完成；若工作流失败，修复后重新构建，不能留下部分成功的正式 Release。
