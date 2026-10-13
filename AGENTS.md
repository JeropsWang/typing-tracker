# Sariana agent instructions

开始修改前阅读 `docs/agent.md`、`docs/architecture.md` 和目标业务模块的 `api.py`；先检查当前分支和工作区，保留已有用户修改。`docs/README.md` 是文档导航。

- 使用 Python/PySide6 Widgets/SQLite 的模块化单体；不引入 Redis、ORM、DI 框架或新界面技术作为普通维护的一部分。
- 新业务代码通过 `app/modules/<业务>/api.py` 协作；跨模块流程放入 `app/workflows/`，依赖装配放入 `app/bootstrap/`。
- 生产 UI 使用 Presenter/只读展示模型/异步命令，不持有 DataSession 或 SQLite 连接。数据库只在 ApplicationWorker 使用；后台不访问 QWidget。
- 写入由 UnitOfWork 统一提交。事务内不请求网络；重试使用稳定操作 ID。统计提交成功后才能确认版本，UI 庆祝也必须在提交成功后触发。
- 保留 tw、评分差异、奖励上限、日切、输入隐私、单实例和旧数据目录行为。新增迁移版本时保留旧库备份与失败回滚。
- 修改代码运行相关回归和 `scripts/check_architecture.py`；事务、恢复、异步或模块接口变化同时检查架构测试与真实桌面工作线程测试。必要时运行全量回归和自检。
- 文档改动检查引用、路径和命令即可。代码改变架构或维护流程时同步更新 docs。
- 使用隔离测试数据，不修改用户真实数据或输出密钥。未经明确请求，不提交、推送或发布；报告实际验证结果与未验证项。

详细命令、任务模板与验证范围见 `docs/agent.md`。用户在本次会话中的明确指示优先于此文件。
