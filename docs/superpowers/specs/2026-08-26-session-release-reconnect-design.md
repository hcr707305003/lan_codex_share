# Session 释放与重新连接设计

## 目标

允许网页主动释放桥接器对指定 Codex Session 的写入连接，使本机 Codex 客户端能够重新打开该 Session。释放不会删除 Session、聊天历史或工作区文件，也不会关闭共享服务、App Server、目录连接或其他 Session。

## 状态模型

每个已加载 Session 增加显式的 `released` 连接状态：

- `connected`：桥接器持有该 Session 的 Codex 连接，可以发送任务；
- `released`：桥接器已关闭该 Session 的 Codex RPC，只保留内存中的历史投影；
- `connecting` / `disconnected`：沿用现有连接中或异常状态。

网页快照读取已释放 Session 时不得隐式调用恢复接口，因此浏览器轮询和多个打开页面都不会重新占用 Session。只有显式“重新连接”操作才能从 `released` 返回 `connected`。

## 安全约束

只有同时满足以下条件时才允许释放：

- 没有正在处理的任务；
- Codex 没有检测到外部活动 Turn；
- 等待队列为空。

不满足条件时返回可读错误，不取消任务、不清空队列、不关闭连接。释放、发送、调整模型和重新连接通过同一个 Session 生命周期锁串行化，避免释放与新消息同时发生。

已释放状态禁止发送消息、调整模型、重新同步和取消任务；单纯读取网页历史和文件预览仍然可用。

## 后端接口

- `POST /api/session/release`：释放请求中的 `session_id`，返回 `released` 布尔值。
- `POST /api/session/reconnect`：显式恢复请求中的 `session_id`，重新读取真实 Session 并返回 `reconnected` 布尔值。

重新连接失败时保持 `released`。如果 Session 已被本机 Codex 客户端占用，直接显示 App Server 返回的占用错误，不创建替代 Session。

释放和重新连接都会广播 Hub 更新，使所有网页同步状态。

## 页面交互

目录模式的每个 Session 行拆分为主选择按钮和独立连接操作按钮：

- 已连接且空闲：显示“释放 Session”；
- 已释放：显示“重新连接 Session”；
- 正在处理、存在队列或连接异常：释放按钮禁用或不显示。

点击连接操作按钮不切换当前 Session，因此用户切换到新 Session 后仍可释放上一项。触屏上按钮保持至少 44px 操作区域，桌面端在悬停和键盘聚焦时清晰可见。

更多菜单为当前 Session 提供同样的“释放当前 Session”或“重新连接 Session”操作，兼容固定 Session 列表模式。当前 Session 被释放后：

- 历史保持可见；
- 连接状态显示“已释放”；
- 输入框、发送按钮和模型设置禁用；
- 状态区域提示可在本机 Codex 客户端打开，或点击重新连接恢复网页操作。

## 验证

- 服务测试覆盖空闲释放、活动任务拒绝、队列拒绝、释放后禁止提交、显式重连和重连失败保持释放。
- Hub 与 Web 测试覆盖目标 Session 路由、接口响应和多页面状态广播。
- 浏览器验证侧边栏非当前 Session 释放、当前 Session 释放、轮询不自动重连、重新连接，以及桌面和 375px 移动布局。
- 本次不修改版本号、不创建标签、不构建原生安装包。
