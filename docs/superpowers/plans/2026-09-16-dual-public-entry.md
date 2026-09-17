# Dual Public Entry Implementation Plan

**Goal / approved design:** cloudflare_origin 与 frp_origin 分别设置，可均空、任选一个或同时回源同一 Share 端口。旧 public_origin 独立配置继续兼容，与新字段混用时报错。

**Architecture:** lan_access 统一规范化入口并按请求 Host 选择唯一入口；来源校验、Cookie Secure、反代转发协议均使用所选入口而不是第一个配置。cloudflare_origin 仅 HTTPS；frp_origin 支持已有规范 HTTP IPv4 或 HTTPS 入口。有效入口中含 HTTP 时要求非空项目密码。相同 Host authority 不能对应不同协议，避免无法判断回源协议。

**Scope:** 仅项目；延续前次未提交 frp 适配，不动真实配置，不启动外部服务、不连接真实公网、不自动提交发布。覆盖前次计划中仅一个公网入口的限制。

## Tasks

- [x] 测试 config 零/单/双入口，旧字段兼容、混用拒绝、类型/HTTPS 限制、协议歧义拒绝。
- [x] lan_access.py 增加 normalize_entry_origins，request_origin 兼容旧字符串与多个入口；配置模型增加独立字段和 public_origins 属性。
- [x] lan_web.py、dynamic_proxy.py、lan_main.py 使用全部入口，按实际 Host 选择协议并逐项显示公网地址；保留回环限制和 HTTP 密码限制。
- [x] 同一 HTTP 测试服务器同时接收 CF/frp 请求，分别验证 Cookie Secure、CSRF、文件、SSE、代理 HTTP/HTTPS 转发协议，跨入口 Origin 拒绝；LAN 仍可访问。
- [x] 示例/README/版本包说明删除二选一表述，说明独立启停、旧字段迁移、同一项目密码与浏览器分别登录、HTTP 明文风险。全量 pytest、git diff --check。

## Verification

全量 337 项测试通过；四种入口组合均验证只接受已配置公网地址，同一服务器上的两个入口完成登录、消息、文件、SSE 和反代协议测试。未更改真实配置、启动隧道或业务服务、连接实际公网或提交发布。
