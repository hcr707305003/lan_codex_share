# 历史删除后恢复 Share 接管

问题：长短历史删除都释放原生 writer，校验完成后仅保留 released 状态，桌面端因而可以继续输入。

实现：记录 release_session 是否实际释放了 Share 的连接。编辑并校验成功、退出文件写锁后，恢复该连接并保留已分页校验的历史，不重新请求全量 thread/read。原本已释放的会话继续保持释放。接管失败单独报告，删除结果仍为成功，备份仍保留。

测试：长短路径、原已释放、接管失败、同 ID、分页历史保留；恢复期间队列锁不阻塞快照。隔离 CODEX_HOME 验证接管后的原生 writer 拒绝第二个写入客户端，不接触用户真实会话。

验证：59 项 Python 与 8 项内联选择测试通过。`tests/probes/history_reacquire_native.py` 使用临时 CODEX_HOME、30 轮记录和 120 次压缩验证生产删除流程：删除两条后恢复同 ID writer；第二端 resume 被拒；主动释放后可从第二端 resume。未发送模型请求，未修改用户真实会话。通过报告保存在 `C:/Users/Administrator/AppData/Local/Temp/codex-history-reacquire-h4cjeqzy/report.json`。
