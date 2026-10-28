# 桌宠占卜（0.9.8）

从桌宠轮盘或右键菜单打开占卜，输入去除首尾空白后 1—50 字的问题。只发送本次主动问题，不搜索、不读取兴趣或被动输入。结果为娱乐性估计，不代表校准概率。

模型返回 `{"yes":80,"uncertain":10,"no":10}`。字段必须完整且唯一，值为 0—100 的整数且总和为 100；拒绝布尔值、小数、附加文字及额外字段，不补数或归一化。最高比例并列时结论为“不确定”。

优先请求服务端结构化输出；格式纠错和明确不支持结构化参数的降级共用一次追加请求预算。正常一次请求，鉴权、限流和超时不自动重试。私有思考不展示或记录。

公共 API 提供不可变 `OracleResult`；`CompanionAgent.judge(config, question, progress)` 返回请求 ID 和结果 Future。与搜索、来信共用准入和所有者取消，跳过搜索配置校验。取消等待实际 I/O 结束后释放准入；迟到结果不重新弹窗。

原生 Widgets 显示三段占比、百分数及娱乐说明，结果仅保留在会话内存，不进入来信历史。本版不新增数据库迁移，保持 schema 3。

验证入口：`scripts/test_companion_oracle.py`、`scripts/test_companion_oracle_ui.py`、`scripts/test_companion_098_release.py` 和 `scripts/test_desktop_architecture.py`。夹具测试不代表真实模型供应商已验收。
