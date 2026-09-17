# FRPC Single Entry Implementation Plan

**Goal:** 用户确认通过 frps 的一个业务端口（示例 20000）转发本机 Share 9000，复用动态多服务反代。

**Architecture:** public_origin 扩展为显式 HTTP IPv4 入口，保留现有 HTTPS 域名行为。HTTP 模式必须设置非空白密码；所有公网回源仍限同机回环，Host 和 Origin 按完整入口校验，不信任转发头。frpc 为外部程序，提供示例配置和手动启动脚本，不自动安装、连接公网或管理业务服务。

**Tech Stack:** Python 标准库、TOML、POSIX sh、Windows cmd、pytest。

**Constraints:** 仅修改 lan_codex_share；不修改真实配置，不保存用户提供的 IP/token，不提交发布或启动真实服务。使用文档专用 IP 192.0.2.10；控制端口 7000 与业务端口 20000 区分。仅一个 public_origin，不宣称同时支持两个公网域名。

## Tasks

- [x] tests/test_frp_access.py：HTTP IP 正常解析，错误协议/地址/凭据/路径/端口拒绝；空密码配置和直接构造均拒绝；HTTP 登录、消息、SSE、文件和跨端口代理继续受认证及来源约束。
- [x] lan_access.py、lan_config.py、lan_web.py：复用 normalizer，默认 HTTP 80/HTTPS 443 规范化，校验 HTTP 密码，保留公网回环限制和基于入口协议的 Cookie Secure 行为。
- [x] lan_main.py：HTTP 公网启动输出浏览器到服务器链路明文警告。
- [x] frpc.example.toml、start_frpc.cmd/sh：单个 TCP 代理到 127.0.0.1:9000；外部 frpc 优先同目录后 PATH，默认同目录 frpc.toml，可传配置路径；缺少程序/配置返回清晰错误，不后台启动、不写 token。
- [x] .gitignore 忽略 frpc.toml/frpc.local.toml/frpc/frpc.exe；文档解释控制端口、业务端口、30 天登录、IP Cookie 不按端口隔离、HTTP 风险及 frp TLS 范围；不新增发版或打包行为。
- [x] pytest 全量、脚本带空格路径/退出码/缺失配置测试、git diff --check。隔离测试不访问真实 frps 或后端。

## Results

- 318 项全量回归通过，包含 20 项新增 frp 入口和脚本测试。
- HTTP 假公网 Host 经回环连接访问登录、消息、SSE、文件及两个不同本地测试服务均验证通过，错误来源和无密码模式拒绝。
- Git Bash 验证默认/自定义带空格配置路径和退出码；Windows cmd 验证缺少配置不会交互阻塞。
- 未修改真实配置、连接实际 frps、启动业务服务、提交或发布。真实网络连通性需用户更新配置并手动启动后验证。
