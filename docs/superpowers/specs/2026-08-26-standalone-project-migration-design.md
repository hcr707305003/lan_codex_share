# 独立项目迁移设计

## 目标

将局域网共享 Codex 会话整理为独立、可公开提交的项目，项目根目录和 Python 包统一使用 `lan_codex_share`，不再保留旧桥接器名称。

## 结构

- `lan_codex_share/`：服务端、Codex App Server 客户端和网页静态资源。
- `tests/`：不依赖真实 Session 或个人目录的自动化测试。
- `runtime/`：仅保留 `.gitkeep`；会话状态、日志和上传文件由 Git 忽略。
- `lan_config.example.toml`：公开配置模板。
- `lan_config.toml`：本机配置，由 Git 忽略。
- 两个 `.cmd`：启动共享服务和打开同一 Session 的本机 CLI。

## 迁移边界

迁移源码、测试、公开文档和启动入口。不迁移虚拟环境、缓存、日志、聊天历史或上传文件。旧服务保持运行，新项目不自动启动；用户手动切换后再清理旧目录。

## 验证

- 新项目中不存在旧包名、个人路径或公开的真实 Session ID。
- 新包可导入，两个启动入口指向新包。
- 本机配置能解析到预期工作区并固定当前 Session。
- 完整测试、Python 编译、JavaScript 语法和依赖检查通过。

