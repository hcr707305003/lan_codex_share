# 流水线构建与版本发布

本文面向仓库维护者，说明如何通过 GitHub Actions 测试代码、构建五个平台的原生版本包并发布 GitHub Release。

## 流水线做什么

工作流文件是 `.github/workflows/release.yml`，触发规则如下：

| 触发方式 | 执行测试 | 构建五平台包 | 创建或更新 Release |
| --- | --- | --- | --- |
| 推送 `main` | 是 | 否 | 否 |
| Pull Request | 是 | 否 | 否 |
| 手动运行 | 是 | 否 | 否 |
| 推送 `vX.Y.Z` 标签 | 是 | 是 | 是 |

标签流水线依次执行：

1. 在 Python 3.11 环境安装开发依赖并运行全部测试。
2. 验证 Git 标签、程序版本和 `docs/releases/vX.Y.Z.md` 一致。
3. 分别构建 Windows x64、Linux x64、Linux ARM64、macOS Intel 和 macOS Apple Silicon 可执行文件。
4. 对可执行文件运行 `--version`、`--help` 和 `cli --help` 冒烟测试。
5. 将程序、示例配置和使用说明组装成各平台 ZIP。
6. 生成 `SHA256SUMS.txt`，创建或更新同名 GitHub Release。

## 首次配置仓库

GitHub Actions 使用仓库自带的 `GITHUB_TOKEN` 创建 Release，不需要额外添加访问令牌。仓库需要满足以下条件：

- GitHub Actions 已启用；
- 工作流拥有 `contents: write` 的 Release 任务权限；
- 默认分支为 `main`；
- 维护者拥有推送主分支和 `v*` 标签的权限。

本机发布建议安装 GitHub CLI 并完成登录，以便检查流水线和 Release：

```sh
gh auth status
```

## Release Notes 规则

每个标签必须有对应的 `docs/releases/vX.Y.Z.md`。它会直接成为 GitHub Release 正文，不再使用自动生成的提交列表。

只记录用户能感知的功能变化：

- 新增功能；
- 功能修复；
- 行为或兼容性变化；
- 必要的升级提示。

不要记录纯文档修改、测试补充、内部重构、例行依赖升级或不影响程序行为的流水线调整。如果内部变化影响安装、启动、配置、兼容性或实际操作，应描述它给用户带来的结果，不描述内部实现过程。

建议模板：

```markdown
# vX.Y.Z

## 新增功能

- 新增了什么功能，以及用户如何使用。

## 功能修复

- 修复了什么可复现问题，修复后表现如何。

## 行为或兼容性变化

- 哪项默认行为、配置语义或平台兼容性发生变化。

## 升级提示

- 升级后必须执行的配置调整或重启操作；没有则删除本节。
```

允许删除没有内容的分类，但至少保留一个包含真实功能条目的分类。校验脚本会拒绝错误版本标题、缺失文件和只有空模板的说明：

```sh
python scripts/check_release_notes.py v0.1.1
```

## 发布一个新版本

以下示例把版本号 `0.1.2` 发布为标签 `v0.1.2`，请替换成实际版本。

### 1. 更新程序版本

修改 `lan_codex_share/__init__.py` 中的 `__version__`：

```python
__version__ = "0.1.2"
```

版本号采用 `主版本.次版本.修订号`：

- 不兼容的配置或命令行为变化提升主版本；
- 向后兼容的新功能提升次版本；
- 向后兼容的问题修复提升修订号。

### 2. 编写功能版本说明

新增 `docs/releases/v0.1.2.md`，按上面的范围详细说明新增、修复、行为变化和升级要求。内容应站在使用者角度，避免只写提交标题或内部类名。

### 3. 在本机验证

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe scripts\check_version.py v0.1.2
.\.venv\Scripts\python.exe scripts\check_release_notes.py v0.1.2
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q lan_codex_share scripts tests
node --check lan_codex_share\web\app.js
git diff --check
```

macOS/Linux：

```sh
./.venv/bin/python scripts/check_version.py v0.1.2
./.venv/bin/python scripts/check_release_notes.py v0.1.2
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q lan_codex_share scripts tests
node --check lan_codex_share/web/app.js
git diff --check
```

### 4. 提交并验证主分支

```sh
git add lan_codex_share/__init__.py docs/releases/v0.1.2.md
git commit -m "release: prepare v0.1.2"
git push origin main
gh run list --branch main --limit 5
```

等待主分支的 `test-and-release` 工作流通过后再创建标签。不要从尚未进入 `main` 的本地提交发布。

### 5. 创建并推送标签

```sh
git switch main
git pull --ff-only origin main
git tag -a v0.1.2 -m "v0.1.2"
git push origin v0.1.2
```

标签推送后会自动开始五平台构建和 Release 发布。查看进度：

```sh
gh run list --workflow test-and-release --limit 5
gh run watch <运行 ID>
```

### 6. 验收发布结果

确认 Release 不是草稿或预发布版本，正文与 `docs/releases/v0.1.2.md` 一致，并包含以下六个文件：

```text
lan_codex_share-v0.1.2-windows-x64.zip
lan_codex_share-v0.1.2-linux-x64.zip
lan_codex_share-v0.1.2-linux-arm64.zip
lan_codex_share-v0.1.2-macos-x64.zip
lan_codex_share-v0.1.2-macos-arm64.zip
SHA256SUMS.txt
```

可使用以下命令核验：

```sh
gh release view v0.1.2
gh api repos/<owner>/<repo>/releases/tags/v0.1.2 --jq '.assets[].name'
gh release download v0.1.2 --pattern SHA256SUMS.txt --output -
```

## 流水线失败处理

先打开失败任务日志，按阶段定位：

- `test` 失败：修复测试、依赖安装或语法问题，推送主分支重新验证。
- `Validate version` 失败：同步程序版本与标签。
- `Validate release notes` 失败：新增或修正对应版本说明。
- `Build executable` 失败：检查 PyInstaller 配置和目标平台依赖。
- `Smoke test executable` 失败：先在对应系统运行生成的程序，排查启动时依赖或参数解析。
- `release` 失败：检查 `contents: write` 权限、GitHub 服务状态和产物下载日志。

如果只是 GitHub Runner、网络或上传的临时故障，可重试失败任务：

```sh
gh run rerun <运行 ID> --failed
```

Release 任务可重复运行：已存在的 Release 会同步版本正文，并覆盖同名资产。

如果标签校验暴露了真实内容错误，并且 Release 尚未创建、标签也没有被他人使用，可以修复主分支后删除错误标签并重新创建。已经公开发布的标签不要移动或复用，应修复代码后发布新的修订版本。

## 回滚

不要强制移动已经发布的标签，也不要用旧产物覆盖一个已被用户下载的版本。功能需要回滚时，在主分支创建还原提交，更新版本号和功能说明，然后发布新的修订版本，例如用 `v0.1.3` 还原 `v0.1.2` 的问题，并在 Release Notes 的“功能修复”中说明影响。

只有发布内容包含敏感信息或存在立即危害时，才应临时撤下 Release；随后仍应创建新版本恢复正常发布链路。
