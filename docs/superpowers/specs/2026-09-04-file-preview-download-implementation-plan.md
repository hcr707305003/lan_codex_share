# 文件预览下载实施计划

## 成功标准

- 右侧文件预览标题栏按“刷新 → 下载 → 关闭”显示操作按钮。
- 只有最新一次文件预览成功后下载按钮才可用；加载、失败、关闭及请求被替换时不会保留旧下载地址。
- 下载接口返回源文件的完整字节、正确 MIME 类型、长度和附件文件名。
- 下载与预览共用工作区边界、`preview_roots`、类型、大小及可选密码认证规则。
- 桌面和窄屏布局不溢出，下载按钮可通过键盘操作且窄屏触控区域至少为 44px。
- 所有目标测试和完整回归测试通过，不改版本号、不打包。

## 任务一：先补服务端失败测试

修改 `tests/test_lan_web.py`：

1. 在工作区文件路由测试中增加 `/api/files/download` 请求。
2. 断言响应正文与源文件字节完全一致。
3. 断言 `Content-Type`、`Content-Length` 和 `Content-Disposition: attachment`。
4. 使用包含中文和空格的文件名，断言 UTF-8 文件名参数正确编码。
5. 断言授权目录外路径仍返回 `403`，不支持类型和超限文件沿用预览错误。
6. 把下载接口加入密码认证保护路由集合，并验证有效 Cookie 可以下载。
7. 先运行目标测试，确认它们因路由尚未实现而失败。

## 任务二：实现受控下载接口

修改 `lan_codex_share/lan_web.py`：

1. 在认证校验后的 GET 路由中加入 `/api/files/download`。
2. 提取或复用动态 `preview_roots` 刷新与 `WorkspaceFileViewer.open()` 校验逻辑，避免预览和下载形成不同权限路径。
3. 下载成功时读取已校验文件的字节，使用预览对象的 MIME 类型返回。
4. 设置 `Content-Disposition: attachment; filename*=UTF-8''...`，保留 Unicode 文件名。
5. 复用 `_send_bytes` 输出准确长度和现有安全响应头。
6. 运行服务端目标测试，确认新增用例通过且原预览接口行为不变。

## 任务三：先补前端结构与状态测试

修改 `tests/test_lan_web.py` 中现有页面资源断言：

1. 断言 `file-preview-download` 位于刷新与关闭控件之间。
2. 断言下载控件具有 `aria-label="下载当前文件"`、工具提示和初始不可用状态。
3. 断言 JavaScript 包含独立下载 URL 生成函数，以及加载、成功、失败和关闭时的状态更新。
4. 断言 CSS 保持现有操作区布局，并在窄屏继承 44px 操作尺寸。
5. 先运行目标测试，确认它们因控件尚未加入而失败。

## 任务四：实现下载按钮和前端状态流

修改 `lan_codex_share/web/index.html`、`lan_codex_share/web/app.js` 和必要时的 `lan_codex_share/web/style.css`：

1. 在刷新与关闭之间增加使用现有图标按钮样式的下载链接，采用标准下载箭头 SVG。
2. 页面初始化时移除可导航地址，设置不可用语义并阻止键盘和鼠标触发。
3. 增加 `/api/files/download?path=...` URL 生成函数，继续使用 `URLSearchParams` 编码路径。
4. `openFilePreview` 每次开始时先禁用下载；仅最新请求成功完成后才写入下载 URL 并启用。
5. 预览失败、关闭面板、切换请求或认证失效时清除下载 URL。
6. 不改变已渲染文件内容、面板滚动位置和当前预览请求逻辑。
7. 复用 `.icon-button` 的焦点、悬停与窄屏样式；仅补充链接禁用态所需的最小 CSS。

## 任务五：完整验证

1. 运行下载与文件预览目标测试：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest tests/test_lan_web.py -q
   ```

2. 运行完整测试：

   ```powershell
   .\.venv\Scripts\python.exe -m pytest -q
   ```

3. 检查前端语法：

   ```powershell
   node --check lan_codex_share/web/app.js
   ```

4. 检查 Python 编译与补丁格式：

   ```powershell
   .\.venv\Scripts\python.exe -m compileall -q lan_codex_share tests
   git diff --check
   ```

5. 浏览器验证 Markdown、代码、图片和 PDF 下载，确认中文文件名、预览保持、桌面布局和窄屏触控尺寸。
6. 检查提交只包含本功能代码、测试和规格，不包含本机配置、日志、构建产物或发行包。

## 任务六：提交范围

1. 单独提交实施计划。
2. 功能实现与测试通过后提交源码。
3. 不更新版本、不生成安装包、不创建标签或 Release；是否推送由当前任务要求决定。
