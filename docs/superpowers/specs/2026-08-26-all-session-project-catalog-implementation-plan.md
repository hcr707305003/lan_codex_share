# 全 Session 项目目录实施计划

## 任务 1：区分配置模式

修改 `lan_config.py`，明确表示以下四种模式：

1. 未配置 `session_ids` 和 `session_id`：单会话自动模式。
2. 显式 `session_ids = []`：全部 Session 目录模式。
3. 非空 `session_ids`：固定 Session 列表模式。
4. 旧版 `session_id`：单个固定 Session 模式。

先补配置回归测试，再调整数据模型和 README 配置说明。验证未配置与显式空数组不再被折叠为同一个值。

## 任务 2：实现 Session 目录客户端

在 App Server 客户端层增加只负责目录发现的组件：

1. 复用现有 JSON-RPC 初始化和远程 App Server 连接。
2. 调用 `thread/list`，使用 `nextCursor` 读取全部分页。
3. 请求未归档任务，并在客户端排除 `ephemeral = true` 和带 `parentThreadId` 的子任务。
4. 按 Session ID 去重，按 `recencyAt`、`updatedAt`、`createdAt` 的优先级降序排列。
5. 校验响应结构；失败时抛出不包含用户消息内容的明确错误。

使用伪 App Server 和单元测试覆盖多页、空目录、重复值、过滤和无效响应。

## 任务 3：动态 Hub 与按需 Session 服务

扩展 `LanSessionHub`，同时支持现有静态服务模式和新的目录模式：

1. 保存目录元数据、项目分组和已连接服务缓存。
2. 首次访问 Session 时，通过工厂创建 `LanChatService`；并发访问同一 Session 时只创建一次。
3. 使用 Session 元数据中的真实 `cwd` 创建 `CodexClient` 和状态文件。
4. 目录中的未连接 Session 返回元数据状态；已连接 Session 返回实时状态、队列和错误。
5. 后台定时刷新目录并广播变化；刷新失败保留最后一次成功结果。
6. 单个 Session 启动失败只记录在对应 Session，不影响其他服务。
7. 关闭 Hub 时停止刷新线程并关闭所有已连接服务和目录客户端。

测试项目分组、默认选择、并发复用、失败隔离、目录更新和干净关闭。

## 任务 4：启动模式与文件授权

重构 `lan_main.py` 的服务装配：

1. 单会话自动和固定列表继续使用当前静态装配。
2. 全部 Session 目录模式创建目录客户端和按需服务工厂，不自动创建新 Session。
3. 按需服务使用 Session 的 `cwd`，而非默认 `workspace`。
4. 目录发现的项目目录动态加入文件预览允许根目录。
5. 启动输出明确显示当前是“全部 Session 目录模式”以及已发现数量。

为动态预览根目录增加边界测试，确保只加入目录中实际出现的绝对 `cwd`。

## 任务 5：项目 → Session 网页导航

更新网页快照结构和左侧栏：

1. 快照返回项目数组，每个项目包含稳定 ID、显示名、路径和 Session 摘要。
2. 左侧栏渲染可折叠项目，Session 显示名称、短 ID、连接/处理/排队状态。
3. 当前 Session 高亮；选择后更新 URL 并按现有流程加载历史。
4. 顶部 Session 下拉框在目录模式隐藏，在静态模式保留兼容。
5. 空目录、目录错误和单 Session 加载失败提供明确状态。
6. 响应式布局下项目导航仍可滚动，移动端选择后自动收起侧栏。

补 Web 路由与静态资源断言，使用浏览器验证桌面和窄屏交互。

## 任务 6：回归、文档与交付

更新 `README.md` 和 `lan_config.example.toml`：

- 解释空数组会共享本机全部未归档主 Session。
- 提醒所有发现项目的文件会对局域网访问者开放。
- 说明固定数组和未配置时的兼容行为。

执行：

```text
python -m pytest -q
python -m compileall -q lan_codex_share tests
git diff --check
```

随后进行本地页面冒烟验证，提交功能改动并推送 `main`。发布补丁版本 `v0.1.1`，等待五个平台构建和 Release 全部成功，确保可下载原生包包含本次功能。
