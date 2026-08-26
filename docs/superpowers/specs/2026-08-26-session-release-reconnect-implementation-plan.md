# Session 释放与重新连接实施计划

## 1. Session 生命周期

- 在 `LanChatService` 中增加 `released` 状态。
- 复用现有队列锁串行化释放、发送、模型调整、同步和重连。
- 仅在无活动任务且队列为空时关闭目标 Session 的 Codex RPC。
- 重新连接失败时再次关闭 RPC，并保持 `released`。

## 2. Hub 与 Web API

- 为 Hub 增加按 Session 路由的释放和重连方法。
- 新增 `/api/session/release` 和 `/api/session/reconnect`。
- 保持现有 CSRF、局域网访问控制和错误响应方式。

## 3. 页面状态与操作

- 在任务菜单加入当前 Session 的释放/重连操作。
- 目录模式的每个已加载 Session 行加入独立操作按钮，点击时不切换 Session。
- 显示“已释放”状态，并禁用当前 Session 的输入和模型设置。

## 4. 验证与交付

- 测试空闲释放、活动任务拒绝、释放后禁止提交、重连成功与失败。
- 测试 Hub 路由和 Web API。
- 在双 Session 桌面端和 375px 移动端验证非当前 Session 释放、轮询不重连和显式重连。
- 提交并推送源码；不修改版本、不创建标签、不构建发布包。
