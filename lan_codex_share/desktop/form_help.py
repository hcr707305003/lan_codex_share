"""Static, value-free field descriptions shared by desktop configuration forms."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QLayout, QSizePolicy, QWidget


FIELD_HELP = {
    'lan': {
        'workspace': 'Codex 操作项目的工作目录；相对路径以本配置文件所在目录为基准。',
        'host': 'Share 监听的网络地址；0.0.0.0 允许通过各网卡访问，127.0.0.1 仅限本机。',
        'port': '浏览器访问 Share 的本地端口；保存变更会尝试同步匹配的隧道回源。',
        'app_server_port': '本机 Codex App Server 通信端口，不是网页端口；必须与 Web 端口不同。',
        'session_ids': '指定会话仅共享列表；共享全部会发现所有可共享会话；自动单会话复用或创建一个会话。',
        'permission_mode': '控制 Codex 的文件访问范围：只读、工作区可写或完全权限；完全权限可操作工作区外文件。',
        'password': '访问共享网页时的登录密码；留空不要求登录，请勿无密码开放公网。',
        'notify_on_task_complete': '任务结束后在网页显示需手动关闭的提示；默认关闭，不是系统通知。',
        'preview_roots': '额外允许网页预览和下载文件的目录；移除列表项不会删除磁盘文件。',
        'cloudflare_origin': 'Cloudflare 的完整 HTTPS 公网入口；留空关闭此入口，不会自动启动 Tunnel。',
        'frp_origin': 'FRP 的完整公网访问地址；HTTP 入口必须设置项目密码，留空关闭此入口。',
    },
    'frp': {
        'proxies.name': 'frps 用来区分代理的名称；随机生成可降低重名概率，名称不等于公网端口。',
        'serverAddr': '部署 frps 的服务器 IP 或域名，不带协议、端口或路径。',
        'serverPort': 'frpc 连接 frps 的控制端口，须与服务端 bindPort 一致；不是浏览器访问端口。',
        'auth.token': 'frpc 与 frps 之间的认证密钥，须与服务端一致；不是 Share 项目密码。',
        'transport.tls.enable': 'true 加密 frpc 到 frps 的传输；不会把浏览器访问的 HTTP 入口变成 HTTPS。',
        'proxies.localIP': 'frpc 能访问到的本地服务地址；同机通常为 127.0.0.1，容器中需按网络环境填写。',
        'proxies.localPort': 'frpc 要转发的本地服务端口；可应用已保存的 Share 端口，不改变其他端口。',
        'proxies.remotePort': '在 frps 服务器上对外开放的业务端口；须在允许范围内，且不与其他代理冲突。',
    },
    'cf': {
        'tunnel': '已创建的 Cloudflare Tunnel ID 或名称，应与所选凭证属于同一个隧道。',
        'credentials-file': '本地管理 Tunnel 的 JSON 凭证文件，不是 Token 文本文件；选择文件不会读取或展示内容。',
        'hostname': '对外访问的域名，例如 codex.example.com；不填 https://、端口或路径。',
        'service': 'cloudflared 转发请求的 HTTP(S) 回源地址；使用 Share 地址只更新当前草稿。',
        'ingress': '选择已有域名规则进行编辑；其他入口、路径规则和默认兜底规则保持不变。',
    },
}


def with_field_help(control, editor, kind, key):
    description = FIELD_HELP[kind][key]
    editor.setAccessibleDescription(description)
    # Expand the field column independently of compact combo/checkbox controls.
    container = QWidget()
    policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    policy.setHeightForWidth(True)
    container.setSizePolicy(policy)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    if isinstance(control, QLayout):
        layout.addLayout(control)
    else:
        layout.addWidget(control)
    note = QLabel(f'{key} · {description}')
    note.setTextFormat(Qt.PlainText)
    note.setWordWrap(True)
    note.setObjectName('muted')
    note.setProperty('help_key', key)
    # Preserve height-for-width when replacing QLabel's word-wrap size policy.
    note.setSizePolicy(policy)
    layout.addWidget(note)
    return container
