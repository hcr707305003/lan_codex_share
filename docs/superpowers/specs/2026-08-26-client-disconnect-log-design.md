# 客户端断连日志降噪设计

## 背景

Windows 浏览器或网络组件主动中止 HTTP keep-alive 连接时，Python `ThreadingHTTPServer` 可能在读取下一条请求行期间抛出 `ConnectionAbortedError`。异常发生在 `BaseHTTPRequestHandler.do_GET` / `do_POST` 之外，因此现有请求级异常处理无法捕获，`socketserver` 会把完整 Traceback 输出到控制台。

这类异常只表示客户端已经离开，不代表局域网 Codex 共享服务发生业务故障。

## 目标

- 将预期的客户端断连异常降级为单行 INFO 日志。
- 日志包含客户端 IP、端口和 Windows 错误码（存在时）。
- 不再为这些断连输出 Traceback。
- 未知服务端异常继续沿用 Python 默认错误处理并输出完整 Traceback。

## 方案

新增一个 `ThreadingHTTPServer` 子类，并在服务器级 `handle_error` 出口分类异常：

- `ConnectionAbortedError`
- `ConnectionResetError`
- `BrokenPipeError`

上述异常输出一行：

```text
INFO lan.web 客户端 192.168.1.240:3864 已断开连接（WinError 10053）
```

若异常没有 Windows 错误码，则省略括号中的错误码。其他异常交回父类 `handle_error`，保留默认 Traceback。

`LanWebApplication.create_server` 使用这个服务器子类，并复用应用已有 logger，以保持日志名称、级别和格式一致。

## 错误边界

不捕获宽泛的 `OSError`，避免磁盘、套接字配置或服务器内部错误被误判为普通客户端断连。请求处理方法和 SSE 流原有的异常边界保持不变。

## 测试

- 模拟 `ConnectionAbortedError(10053, ...)`，确认只产生一条 INFO 日志且不调用父类错误处理。
- 模拟 `ConnectionResetError` 与 `BrokenPipeError`，确认同样被视为客户端断连。
- 模拟 `RuntimeError`，确认继续委托父类错误处理。
- 运行完整 pytest 回归测试。

## 发布范围

本次只提交源码和测试，不生成或更新发行包。
