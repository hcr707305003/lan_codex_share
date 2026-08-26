# 客户端断连日志降噪实施计划

## 目标

捕获 HTTP Server 读取 keep-alive 后续请求时产生的预期客户端断连异常，将完整 Traceback 替换为单行 INFO 日志，同时保留未知服务器异常的默认错误输出。

## 任务一：建立回归测试

修改 `tests/test_lan_web.py`：

1. 为 `ConnectionAbortedError(10053, ...)` 添加测试，验证日志包含客户端地址和错误码，并且不会调用父类 `handle_error`。
2. 覆盖 `ConnectionResetError` 与 `BrokenPipeError` 的分类行为。
3. 为非断连异常添加测试，验证仍委托父类处理。

## 任务二：实现服务器级异常分类

修改 `lan_codex_share/lan_web.py`：

1. 新增 `ThreadingHTTPServer` 子类。
2. 在 `handle_error` 中读取当前异常。
3. 对三类预期断连异常输出单行 INFO 日志。
4. 错误码不存在时使用不带错误码的日志格式。
5. 其他异常调用父类实现。
6. `LanWebApplication.create_server` 改为创建该子类，并注入应用 logger。

## 任务三：验证

1. 运行新增的目标测试。
2. 运行完整 pytest 测试。
3. 运行 Python 编译检查。
4. 运行 `git diff --check`。
5. 确认未生成发行包、未修改版本号。

## 任务四：提交

提交并推送源码与测试，提交说明聚焦客户端断连日志降噪。
