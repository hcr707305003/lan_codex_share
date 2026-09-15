# Persistent Login Implementation Plan

**Goal:** 用户已批准登录保留 30 天，跨服务及浏览器重启，密码变化后旧登录失效。

**Architecture:** 独立 auth_tokens.py 保存随机签名密钥和带密钥的密码校验标记到配置旁 runtime/lan/auth.json。签名凭证携带签发时间、30 天有效期和随机 nonce，服务端校验签名及时间；密码变化（包括关闭密码）轮换密钥。文件以受限权限原子写入，读取损坏或写入失败时拒绝启动，不关闭认证。

**Constraints:** 仅修改 lan_codex_share，保留前次未提交优化；不启动、重启或停止业务服务；不自动提交、推送或发布。运行时文件不入库、不进入前端缓存，不保存新增明文密码副本。

## Tasks

- [x] tests/test_auth_tokens.py：测试重建实例仍可验证、30 天边界、伪造/畸形/未来凭证、不同目录、密码更改及改回、关闭再开启、损坏文件及写入失败。
- [x] auth_tokens.py：实现 AuthTokens(password, state_path=None)、issue()、verify(token)；未提供路径时使用内存密钥供隔离实例使用。持久文件只在主程序单实例锁内初始化。
- [x] lan_web.py、lan_main.py：接入签名校验，每次成功登录签发独立凭证；Cookie Max-Age=2592000，保留 HttpOnly、SameSite=Strict、公网 HTTPS Secure；保留登录限流与无密码模式。
- [x] tests/test_lan_web.py：真实 HTTP 登录 Cookie 跨服务实例验证、改密码拒绝、认证状态带当前 CSRF 头。web/app.js 在获取登录状态时同步 CSRF，并在重连后刷新，避免旧页面持有重启前的令牌。
- [x] README：记录 30 天固定有效期、升级需登录一次、保留运行目录、改密码/删除密钥撤销和 HTTP 风险；全量 pytest、Node 回归及 git diff --check。

**Verification commands:** `.venv/Scripts/python.exe -m pytest tests/test_auth_tokens.py tests/test_lan_web.py -q`，随后 `.venv/Scripts/python.exe -m pytest -q` 和 `git diff --check`。测试只运行隔离假服务，不调用真实 Codex 或 PHP 服务。
