# Share 端口同步 FRP / Cloudflare

用户确认：FRP 跟随当前 Share 服务端口，不扩展多代理/协议管理。

- 控制台保存已有 Share 配置且有效 Web 端口改变时，同步当前桌面设置指定的 frpc 配置。
- 仅匹配 TCP、无 plugin、loopback localIP、localPort 等于原 Share 端口的规则；所有明确匹配项一起更新。其他规则保持不变。
- 仅改变 localPort；名称、公网端口、控制端口、认证字段、注释保留。
- 用户追加确认 Cloudflare YAML 同步：更新明确指向旧 Share 端口的 HTTP loopback service URL 端口，保留路径、主机、域名及其他规则。忽略有用户信息/查询/片段的 URL；Token 模式提示到 Cloudflare 控制台修改，不写本地 YAML。
- FRP 与 Cloudflare 分别准备和应用，单个隧道失败不阻止另一个。新增 tunnel_port_synced 信号刷新端口信息、标记对应服务需重启。
- 缺省 Share 端口采用运行时默认值 8765。新建配置没有旧端口基线，不猜测同步。
- Share 保存之前读取隧道配置快照；保存成功后使用原有 ConfigDocument 原子写入及摘要冲突保护。配置选择变化也阻止同步。
- Share 保存失败不写隧道配置。隧道配置不存在、无匹配、格式错误或冲突时，保留成功保存的 Share 并明确报告未同步原因。
- 另存副本不触发跨文件同步。表单和高级编辑模式行为一致。
- 不启动、停止或重启服务，不提交或发布。用户已授权按推荐方案连续执行。

验证：正常同步、默认端口、过滤规则、注释保留、文件冲突、写入失败、另存副本及原入口同步回归。
