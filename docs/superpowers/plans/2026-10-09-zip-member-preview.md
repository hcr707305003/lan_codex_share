# ZIP Member Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在右侧面板浏览 ZIP 目录、预览成员并下载成员或整包。

**Architecture:** 保留 WorkspaceFileViewer 的授权检查；独立 ZIP 模块完成受限读取，通过隔离进程执行；HTTP 路由只做认证、参数校验和响应。独立前端模块管理目录、成员及工作表导航，继续复用现有预览面板。

**Tech Stack:** Python zipfile、multiprocessing、psutil、defusedxml；原生 JavaScript/CSS；pytest、node:test。XLSX 仅解析有限的 OOXML 表格值，不新增 Office 运行时或表格依赖。

**Spec:** `docs/superpowers/specs/2026-10-09-zip-member-preview-design.md`

## Global Constraints

- 当前分支开发，保留六个已有未提交文件中的下载修复；只显式暂存本任务文件。
- 不启动、重启、停止用户服务；不推送、不发布、不覆盖运行中的程序。
- 可浏览 ZIP 大小最多 200 MiB、中央目录最多 8 MiB、最多 5,000 条目、路径深度最多 32 层。
- ZIP 声明的总未压缩大小最多 500 MiB，单成员最多 25 MiB、压缩比最多 100:1；检查声明值和实际读取字节数。
- 文本预览最多 2 MiB，DOCX 文本继续使用现有 100,000 字符上限。
- 每次解析最多 30 秒、子进程内存最多 512 MiB；并发解析最多 2 个，繁忙立即拒绝。
- 目录每页最多 100 项；选中工作表最多展示 200 行、50 列。
- 不解压整包到工作区，不跟随链接、不执行公式宏或外部资源，不递归预览嵌套 ZIP。

## Task 1: 受限 ZIP 目录与成员读取

**Files:** 创建 `lan_codex_share/archive_reader.py`、`tests/test_archive_reader.py`。

**Interfaces:**

```python
class ArchiveError(ValueError):
    # status: HTTP status, message: safe Chinese explanation
    pass

def inspect_archive(path: str, version: str = '', directory: str = '', page: int = 0) -> dict:
    # {version, directory, page, total, entries:[{id,name,path,directory,size}]}
    ...

def read_member(path: str, version: str, member: int) -> dict:
    # {name, size, data:bytes}; central-directory index is authoritative
    ...
```

- [ ] 添加 ZIP 测试夹具：使用 zipfile 创建 `企业/方案.xlsx`、`说明.md`、空目录和中文名称；先验证不存在的新模块使测试失败。

```python
def test_member_bytes_and_directory(tmp_path):
    path = tmp_path / 'sample.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('企业/说明.md', '# hello')
    listing = inspect_archive(str(path))
    assert listing['entries'][0]['directory'] is True
    child = inspect_archive(str(path), listing['version'], '企业/')
    member = read_member(str(path), listing['version'], child['entries'][0]['id'])
    assert member['data'] == b'# hello'
```

- [ ] 在调用 ZipFile 前读有界尾部 EOCD，校验单卷、中央目录偏移/大小/条目数；ZIP64 可明确拒绝浏览并保留整包下载。版本标记由文件 stat 身份、mtime_ns、大小及中央目录摘要构造，读取前后检查变化。
- [ ] 校验全部条目名称：统一斜杠、拒绝绝对路径/盘符/UNC/.. /NUL/特殊文件/软链接、规范化重名及文件与目录冲突。用原始成员索引读取，不能按用户输入的成员名称取磁盘文件。
- [ ] 目录按单层构造并排序、分页；成员按固定块读取，计数、检查实际大小与 CRC，不使用 extractall。
- [ ] 添加损坏、重复、路径穿越、超限、修改版本、负索引、目录当文件、加密和高压缩比测试；运行 `pytest tests/test_archive_reader.py -q`。
- [ ] 仅提交该模块和测试，提交信息 `feat: add bounded ZIP member reader`。

## Task 2: 隔离执行与成员格式预览

**Files:** 创建 `lan_codex_share/archive_worker.py`、`lan_codex_share/archive_preview.py`、`tests/test_archive_preview.py`、`tests/test_archive_worker.py`；复用 `document_extract.py` 的 DOCX 文本转换。

**Interfaces:**

```python
def preview_member(path: str, version: str, member: int, sheet: int = 0) -> dict:
    # {kind,name,size,mime,content?,warning?,data?,sheets?,sheet?,rows?,truncated?}
    ...

def run_archive(path: str, action: str, *, version: str = '', member: int = -1,
                directory: str = '', page: int = 0, sheet: int = 0) -> dict:
    # action is list, preview or download; calls corresponding reader in child
    ...
```

- [ ] 先测试繁忙/超时/子进程异常均返回 ArchiveError，且进程、Pipe、并发许可被释放；使用短超时的隔离夹具，不操作真实服务。
- [ ] 使用 spawn 和进程级 BoundedSemaphore(2)，父进程监测 30 秒期限与 RSS 512 MiB。结果先经受限临时结果文件写入（路径由父进程生成），Pipe 只回传小型完成/错误信号，避免大结果阻塞 recv 导致失去超时监控。父进程校验结果大小后读取并清理整个临时目录。
- [ ] preview_member 以扩展名分支：MD/code 文本、图片/PDF 字节、DOCX 纯文本、XLSX 结构化工作表；其他文件返回 download 元信息，不执行内容。DOCX 临时文件由受控临时目录生成，不使用成员路径命名。
- [ ] XLSX 先执行内层 ZIP 安全/大小检查，再用 defusedxml 读取 workbook、relationships、sharedStrings 和选中 worksheet。内部关系只能指向规范化的包内文件，External 不解析；发现宏主体拒绝预览。所有读取均受累计解压大小限制。
- [ ] 按单元格坐标仅生成前 200 行、50 列的矩形有界表格；解析字符串、布尔及数值；公式只读取缓存 v，缺少缓存返回「公式结果未缓存」文本。显式标注日期可能以原始值显示，不追求 Excel 格式还原。

```python
def test_formula_without_cache_is_not_evaluated(xlsx_archive):
    result = preview_member(str(xlsx_archive.path), xlsx_archive.version, 0)
    assert result['rows'][0][0] == '公式结果未缓存'
    assert len(result['rows']) <= 200
    assert all(len(row) <= 50 for row in result['rows'])
```

- [ ] 测试空表、多表、恶意 XML/外链、稀疏大坐标、截断、DOCX 文本、图片/PDF 字节和 CRC 错误；运行 `pytest tests/test_archive_preview.py tests/test_archive_worker.py -q`。
- [ ] 提交新模块和测试，提交信息 `feat: isolate archive previews and read XLSX values`。

## Task 3: HTTP 授权、目录和成员接口

**Files:** 修改 `lan_codex_share/lan_web.py`、`lan_codex_share/workspace_files.py`；创建 `tests/test_archive_web.py`。

**Interfaces:** 三个 GET 路径共用参数 path、version；目录额外 directory/page；成员额外 member；表格额外 sheet。

```text
/api/archives/list?path=...&version=...&directory=...&page=0
/api/archives/preview?path=...&version=...&member=0&sheet=0
/api/archives/download?path=...&version=...&member=0
```

- [ ] 先添加路由测试，验证成功目录响应、成员精确字节及无登录时 401。
- [ ] 三个接口均放在现有认证之后，使用 `_open_workspace_file(path, download=True)` 更新动态授权根并验证 ZIP 的真实文件路径，然后调用 run_archive。入口只接受 `.zip`；所有整数参数必须在对应合法范围内。
- [ ] 普通 ZIP 的 `/api/files/view` 返回 kind=archive 元信息，原包下载保持独立。损坏 ZIP 浏览报错不影响 `/api/files/download`。
- [ ] 成员 JSON 通过 `_json` 返回；图片/PDF 的限定 MIME 可 inline（PDF SAMEORIGIN），其他成员仅 attachment，带 UTF-8 文件名、nosniff、no-store；设置安全错误码而非暴露堆栈。

```python
def test_archive_outside_root_is_denied(server, outside_zip):
    for action in ('list', 'preview', 'download'):
        status, _, _ = request(server, 'GET', '/api/archives/' + action +
            '?path=' + quote(str(outside_zip)) + '&version=x&member=0')
        assert status == 403
```

- [ ] 覆盖目录授权变更、软链接、版本冲突 409、恶意参数、损坏 ZIP 和整包下载；运行 `pytest tests/test_archive_web.py tests/test_workspace_files.py tests/test_lan_web.py -q`。
- [ ] 显式暂存路由、viewer 及下载修复对应测试并提交，不混入前端未完成内容。

## Task 4: 右侧压缩包导航与表格预览

**Files:** 创建 `lan_codex_share/web/archive-preview.js`、`tests/javascript/archive-preview.test.cjs`；修改 `web/app.js`、`web/index.html`、`web/style.css`、`static_assets.py`（如资源清单需要）、已有文档预览测试。

**Interfaces:**

```javascript
// Plain browser module using the repository's existing module-loading convention.
// host supplies DOM container and existing safe rendering helpers.
function createArchivePreview(host) {
  return {open(reference), close()};
}
// reference = {path}; host = {container, renderMarkdown, renderCode, onUnauthorized}
```

- [ ] 先用 node:test 的 DOM/fetch stub 测试版本参数保持、分页、返回目录及迟到响应丢弃。
- [ ] 模块维护 path/version/directory/page/member/sheet、AbortController 和请求序号；每次导航先取消旧请求，成功响应再渲染；close 中撤销对象 URL。
- [ ] app.js 检测 kind=archive 后委托模块；切换普通文件、关闭面板、切换会话均调用 close；整包下载保持原始 reference，成员下载使用独立链接。
- [ ] 目录使用语义化按钮和面包屑，文件下载独立 a 元素；名称全部 textContent。表格最多 10,000 单元格，独立横向滚动，不能撑大侧栏；提供工作表 select、截断提示及下载原文件入口。
- [ ] loading/error/empty 状态可读；键盘聚焦可见；窄屏布局和暗色主题复用现有 CSS 变量，不加入新图标字体或框架。

```javascript
test('late archive response cannot reopen a closed pane', async () => {
  const {viewer, resolve, body} = setupArchivePreview();
  const pending = viewer.open({path: 'C:/sample.zip'});
  viewer.close();
  resolve({version: 'v', entries: []});
  await pending;
  assert.equal(body.children.length, 0);
});
```

- [ ] 运行全部 JS 测试；以本地独立测试页面验证 375px、宽屏、长中文路径、分页、空包、表格切换和返回目录。测试不连接真实 Codex 或用户服务。
- [ ] 提交前端及相关测试，提交信息 `feat: browse archive members in file preview panel`。

## Task 5: 回归、冻结兼容和说明

**Files:** 修改 `README.md`、`tests/fixtures/frozen_document_smoke.py`；根据新增资源验证 `static_assets.py`、两个 PyInstaller spec 和 `.github/workflows/release.yml` 的既有收集规则。

- [ ] README 写明 ZIP/格式范围、安全限额、公式缓存/截断、整包与成员下载差别，不包含私人路径、凭据或业务文件。
- [ ] 冻结冒烟脚本增加自建小型 ZIP 和 XLSX，执行 run_archive 列表/预览/下载；保持 freeze_support 和无服务启动方式。不下载实际业务包、不触发发布。
- [ ] 运行 `pytest -q`、`node --test tests/javascript/*.test.cjs`、`git diff --check`；失败必须定位，不能用放宽安全检查消除失败。
- [ ] 在当前 Windows 环境运行冻结冒烟脚本的本地隔离构建（若用户的「不打包」约束仍适用，则只运行源代码冒烟并明确冻结验证待发布前执行）；其他四个平台仅声明待 CI 验证，不声称已验证。
- [ ] 回看规格逐条核对已完成项，记录实际测试数量和未验证部分；仅提交本任务文件，不推送/发布，不自动重启 Share。

## 自检

## 实施记录（2026-10-09）

- Task 1–3 已完成并本地提交：受限 ZIP 读取、隔离格式预览、授权 HTTP 接口；原包下载不依赖 ZIP 解析成功。
- Task 4 已完成：面包屑、单层分页、独立成员下载、工作表选择、请求取消及对象 URL 清理。浏览器使用独立模拟会话，不连接用户 Codex。已实测宽屏与 375px 窄屏、Excel/空工作表切换；目录返回、分页、迟到响应由自动测试覆盖。未逐一进行全部格式的浏览器人工测试。
- Task 5 已补充 README 和无服务启动的冒烟脚本，覆盖 ZIP 目录、成员下载、DOCX 和 XLSX 缓存值。PyInstaller Share spec 原有整目录 web 收集覆盖新增脚本，Python 模块使用静态导入；未构建冻结程序，Windows 冻结程序与其他平台仍待发布前验证。
- 初轮完整回归：884 项 Python、65 项 JavaScript 全部通过；随后补充子进程错误恢复、外部工作表拒绝和分页测试，最终结果见交付说明。重复成员测试产生的 zipfile warning 为故意构造的测试输入。
- 不自动重启真实服务，不推送、不打包、不发布；保留当前 main 中的本地成果。

任务 1 覆盖容器约束与成员身份，任务 2 覆盖格式和运行资源，任务 3 覆盖授权边界，任务 4 覆盖导航与并发请求，任务 5 覆盖回归/文档/冻结兼容。各接口仅依赖前置任务明确的签名；示例测试中的 server、xlsx_archive、setupArchivePreview 由对应测试任务建立本地夹具。现有下载修复保留并纳入任务 3、4 回归。
