# 原生版本包与统一启动程序设计

## 目标

为 Windows、Linux 和 macOS 发布无需安装 Python 的原生版本包。每个平台的压缩包只提供一个 `lan_codex_share` 主程序，该程序默认启动局域网共享服务，并通过 `cli` 子命令打开本机 Codex CLI。

首个版本为 `v0.1.0`。目标机器仍需安装并登录 Codex CLI，版本包不复制、不修改也不重新分发 Codex CLI。

## 命令接口

默认启动共享服务：

```text
lan_codex_share
lan_codex_share --config=custom.toml
lan_codex_share --config custom.toml
```

打开共享 Session 的本机 CLI：

```text
lan_codex_share cli
lan_codex_share cli --config=custom.toml
lan_codex_share cli --config custom.toml --session 01example
```

程序同时支持：

```text
lan_codex_share --version
lan_codex_share --help
lan_codex_share cli --help
```

未指定子命令时使用 `share` 模式。`share` 可以作为显式子命令使用，但 README 以省略子命令的简洁形式为主。

## 路径规则

程序需要区分可执行文件目录、调用者当前目录和配置目录：

- 未指定 `--config`：读取可执行文件同目录的 `lan_config.toml`。
- 显式绝对配置路径：直接使用该文件。
- 显式相对配置路径：相对于调用者当前工作目录解析。
- `workspace` 与 `preview_roots` 的相对路径：继续相对于配置文件目录解析。
- `runtime/lan`：写入配置文件目录，使不同配置拥有独立日志、上传文件、Session 状态和单实例锁。

源码开发模式下，可执行文件目录定义为仓库根目录。现有 `.cmd` 和 `.sh` 从仓库根目录调用，因此默认行为保持兼容。

## 程序架构

新增统一启动模块，负责：

1. 解析 `share`、`cli`、`--config`、`--session`、`--version` 和帮助信息。
2. 根据是否处于冻结程序中确定可执行文件目录。
3. 解析最终配置路径和配置目录。
4. 将 Share 模式交给现有 `lan_main`，将 CLI 模式交给现有 `lan_cli`。

`lan_main` 和 `lan_cli` 将接收已经解析的配置路径，避免各自再次依赖当前工作目录。Share 模式的运行目录也改为配置目录。核心业务、权限、Session、App Server 和 Web API 行为保持不变。

## 冻结程序资源

使用 PyInstaller `onefile` 模式生成单一主程序。冻结配置必须包含：

- `lan_codex_share/web` 下的 HTML、CSS 和 JavaScript。
- Python 运行时依赖：`websocket-client`、`psutil`、`Pillow` 及其实际导入模块。
- 包版本 `0.1.0`。

Web 资源访问使用兼容源码目录和 PyInstaller 临时解包目录的资源定位方式。运行日志和用户数据不得写入 PyInstaller 临时目录。

## 平台与产物

使用 GitHub Actions 原生 Runner 分别构建：

- Windows x64
- Linux x64
- Linux ARM64
- macOS Intel x64
- macOS Apple Silicon ARM64

每个平台发布一个 ZIP：

```text
lan_codex_share-v0.1.0-windows-x64.zip
lan_codex_share-v0.1.0-linux-x64.zip
lan_codex_share-v0.1.0-linux-arm64.zip
lan_codex_share-v0.1.0-macos-x64.zip
lan_codex_share-v0.1.0-macos-arm64.zip
```

每个 ZIP 包含：

- `lan_codex_share.exe` 或 `lan_codex_share`
- `lan_config.example.toml`
- 面向版本包用户的 `README.md`

Release 另外附带 `SHA256SUMS.txt`，记录五个 ZIP 的 SHA-256。

## 自动发布

新增 GitHub Actions 工作流：

1. 以 `v*` Tag 触发。
2. 校验 Tag 与 Python 包版本一致。
3. 在每个平台安装固定范围的构建依赖并运行测试。
4. 使用 PyInstaller 构建主程序。
5. 执行不启动 Share 服务的烟雾测试：`--version`、`--help`、缺失配置错误和 CLI 参数解析。
6. 组装平台 ZIP 并上传构建产物。
7. 汇总五个平台产物，生成校验和并创建 GitHub Release。

工作流只在 Tag 构建全部 Release。普通分支和 Pull Request 运行 Python 测试及打包配置检查，避免每次提交消耗全部平台构建时间。

## 错误处理

- 默认配置不存在：显示查找的完整路径，并提示复制同目录的 `lan_config.example.toml`，退出码 `2`。
- 显式配置不存在或无效：显示实际解析路径和具体配置错误，退出码 `2`。
- `cli --session` 不在共享列表：沿用现有明确错误。
- 未安装或未登录 Codex CLI：不隐藏底层错误，Share 和 CLI 都使用非零状态码退出。
- 冻结资源缺失：启动时显示资源缺失错误，不启动不完整的 Web 服务。

## 测试

自动化测试覆盖：

- 默认配置位于程序同目录。
- 显式相对与绝对配置路径。
- 配置目录决定运行数据目录。
- 默认 Share 模式和显式 `share` 模式。
- `cli` 模式及 `--session` 参数转发。
- `--config=value` 与 `--config value` 两种写法。
- 源码运行和模拟冻结运行下的资源路径。
- PyInstaller 构建产物的版本、帮助和错误码烟雾测试。
- 现有完整 `pytest` 回归测试。

## 安全与发布边界

- 版本包不包含 `lan_config.toml`、Session ID、日志、上传文件、运行状态或个人路径。
- 示例配置保持通用路径。
- GitHub Release 使用仓库自带的短期 `GITHUB_TOKEN`，不新增长期凭据。
- 第一版不进行 Windows 代码签名和 macOS 公证。README 明确说明未知发布者或 Gatekeeper 提示及用户自行验证 SHA-256 的方法。
- 不自动安装 Codex CLI，不自动登录账号，不修改防火墙，也不启动或管理 PHP 服务。

## 验收标准

- 五个平台均生成命名一致的 ZIP。
- 解压后无需 Python 即可执行 `lan_codex_share --version`。
- `lan_codex_share --config=路径` 可启动指定配置。
- 未提供 `--config` 时只查找主程序同目录的 `lan_config.toml`。
- 同一可执行程序可通过 `cli` 子命令打开本机共享 Session。
- Release 包不包含任何本机数据或敏感配置。
- Tag `v0.1.0` 对应 GitHub Release `v0.1.0`，并带有可验证的 SHA-256 清单。
