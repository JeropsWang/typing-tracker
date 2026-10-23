# 0.9.7 定时来信与双视角记忆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 应用驻留时按用户明确兴趣生成可恢复的定时来信，在桌宠记忆页提供普通用户和开发者共用数据的两个视角。

**Architecture:** 延续模块化单体。companion 拥有纯排期规则、任务和有界报告，ApplicationWorker／UnitOfWork 提交状态；Qt Presenter 协调异步数据库命令和现有 LangGraph 网络服务。应用内记忆使用同一份设置和报告快照；AOCI 为可选开发索引，缺失不影响产品。

**Tech Stack:** Python／PySide6 Widgets／SQLite／现有 LangGraph；不新增依赖、运行服务或界面技术。

**Spec:** [定时来信设计](../specs/2026-10-20-companion-news-design.md)、[双视角记忆设计](../specs/2026-10-20-memory-views-design.md)。用户于 2026-10-20 确认两份设计，随后认可本计划并选择「当前会话顺序实现（推荐）」，执行方式为 Native。

## Global Constraints

- 定时开关默认关闭；每天一个本地时间，默认 09:00；安静时段默认 22:00—08:00，可关闭。
- 兴趣由用户明确填写，1—5 个，每个最多 40 字，总长不超过 200 字；去除空白与重复项。关闭且无兴趣的初始配置合法。
- 30 秒唤醒，仅自动受理当前日有效时刻后两小时内的一项任务；自动 ID 为 `news:YYYY-MM-DD`，与统计凌晨 4 点日切分开。
- 网络开始后的失败／取消／上次中断不自动重试；已生成报告保存失败仅重试存储，沿用任务 ID 与 attempt。
- 6 轮模型、8 次工具、3 次搜索、3 次正文读取、8 来源、合作式 300 秒限额；不按兴趣分别启动图。
- 报告正文上限 12,000 字，来源至多 8 项；保留最近 30 天且最多 100 条终态历史，当日去重记录和在途任务不得被清理。
- 提交后才刷新、通知和庆祝；后台不操作 QWidget，UI 不持有 DataSession，事务内不请求网络。
- 不记录被动输入、私有推理、Key、完整配置或原始工具对话；网页不能自行成为用户偏好。
- 所有新增／修改模块、类、函数、槽和测试夹具有中文功能说明；复用雾紫／冰蓝／珊瑚色与切角纸张，主题切换同步。
- 应用版本升至 0.9.7，数据库迁移至 3；保留旧迁移、在线备份及失败回滚。未经另行请求不提交、推送、打包发布，不接触真实用户数据。

## Review Focus

1. 删除今天的自动来信后再次检查到期，不得因删除内容而重获自动名额（任务 2、6）。
2. 新 attempt 已开始后旧网络回调到达，不能覆盖新结果或取消他人的主动搜索（任务 2、3、4）。
3. 停用排期或修改兴趣发生在领取／保存边界，旧配置结果不能通知，已完成历史保留（任务 2、4）。
4. 只含警告和真实来源的部分报告可以保存；无来源和损坏的存储 JSON 不能伪装成成功记忆（任务 1、2、3、6）。
5. 冻结安装无源码、AOCI 缺失／漂移、中文长文本和窄窗口时仍能阅读用户记忆，且不执行外部索引中的路径或命令（任务 6、7）。

## 文件与执行约定

任务按 1→2→3→4→5→6→7 顺序；每个任务完成红／绿回归后再推进。新增文件均在下列任务归属中，避免把数据库、调度、网络和视觉全部塞进 `agent_controller.py` 或 `agent_settings.py`。

`PY` 表示有效 Python 3.13 解释器：正常环境 `.venv/Scripts/python.exe`，本机为 `.local/runtime/python/python.exe`。嵌入解释器运行 unittest 前显式把仓库根、`scripts`、`.deps` 加入 `sys.path`，不依赖其忽略的 PYTHONPATH；设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`QT_QPA_PLATFORM=offscreen`。文档命令中的 `PY` 需按环境替换。

本计划没有 Git 提交步骤；保留当前已有 AOCI／文档修改。执行前按 using-git-worktrees 检查宿主隔离能力与仓库分支约束，不能为隔离清理或覆盖现有工作。

### Task 1: 纯排期、配置与报告契约

**Files:** 新建 `app/modules/companion/news.py`、`news_codec.py`、`memory.py`、`scripts/test_companion_news_rules.py`；修改 `app/modules/companion/api.py`、`scripts/check_architecture.py`。

**Interfaces:**
- `NewsConfig.from_values(values: Mapping[str, str]) -> NewsConfig`；`settings_values() -> dict[str, str]`；`normalize_interests(text: str) -> tuple[str, ...]`。
- 设置键：`companion_news_enabled/interests/time/quiet_enabled/quiet_start/quiet_end`，兴趣以 JSON 数组保存；`companion_news_updated_at/revision` 由保存用例生成，不信任 UI 自报。
- `scheduled_at(config: NewsConfig, day: date) -> datetime | None` 返回当地墙上时间；`due_plan(config, now: datetime) -> NewsPlan | None`、`next_news_at(config, now) -> datetime | None` 共用安静与两小时规则。边界为 `[有效时刻, 有效时刻+2小时]`；下次时间必须晚于 now。
- `NewsTask`、`NewsClaim`、`NewsRequest`、`MemorySnapshot` 为冻结展示类型。claim 含 `task_id/attempt/config_fingerprint`；request 含明确兴趣与当地日期，不通过 200 字话题参数传长提示。
- `encode_report(report: AgentReport) -> str`、`decode_report(text: str) -> AgentReport` 校验类型、大小、UTC 检索时间和安全来源 URL；`configuration_fingerprint(agent, news, companion_enabled) -> str` 排除凭据。

- [ ] **Step 1:** 写 `test_companion_news_rules.py`，断言去重后最多 5 兴趣、单项 41 字拒绝、总长超 200 拒绝；默认关闭且空兴趣合法，启用后空兴趣拒绝；安静起止相同拒绝。
- [ ] **Step 2:** 运行 `PY -B -m unittest discover -s scripts -p test_companion_news_rules.py -v`，确认因新契约缺失失败。
- [ ] **Step 3:** 实现上述纯契约，将三个纯文件加入 `PURE_FILES`；北京时间示例 `scheduled_at(09:00, 2026-10-20)==09:00`、计划 07:00 顺延至当日 08:00、计划 23:00 顺延跨日则本日返回 None。下次时间只按新的当地日计算，不依赖统计 AppCalendar。
- [ ] **Step 4:** 增补 `test_grace_window_and_clock_rollback`，断言 10:59／11:00 可受理、11:00:01 不受理；`test_report_codec_rejects_missing_sources_and_malformed_rows`，断言 12,001 字／9 来源／私有或带凭据链接拒绝，无效 JSON 返回可读错误；`test_fingerprint_excludes_keys` 断言换 Key 不把凭据或其摘要写入持久化指纹。
- [ ] **Step 5:** 运行本组及 `check_architecture.py`，全部通过。

### Task 2: 迁移 3、任务领取和记忆提交

**Files:** 新建 `app/modules/companion/repository.py`、`news_service.py`、`app/workflows/companion_news.py`、`scripts/test_companion_news_storage.py`；修改 `app/storage/db.py`、`session.py`、`app/modules/companion/api.py`、`scripts/test_architecture.py`。

**Interfaces:**
- `CompanionRepository(conn)` 只提供 SQL，`migrate_news_schema(conn)` 由迁移 3 调用；DataSession 装配 `companion`。
- 单表 `companion_news_tasks`：`id` 主键，`kind/planned_date/planned_time/config_fingerprint/state/attempt/run_id/created_at/started_at/finished_at/error_code/report_json/notified_at/deleted_at`。状态 `waiting/running/completed/failed/cancelled/interrupted`；attempt 单调递增。
- `CompanionNewsService(store, uow, *, run_id)`：`claim(task_id, kind, config_fingerprint, planned_date, planned_time, *, now_utc, retry=False) -> NewsClaim | None`；`release_unstarted(claim) -> bool`；`complete(claim, report, *, now_utc) -> NewsTask`；`fail(claim, error_code, *, now_utc) -> bool`；`accept_notice(task_id, *, now_utc) -> bool`；`forget(task_id, *, operation_id, now_utc) -> bool`；`recover(*, now_utc)`；`prune(*, local_day, now_utc)`。
- `CompanionNewsWorkflow(session, settings_service, *, run_id, local_now)` 对外提供同名异步命令用例，并在事务内用当前 settings、注入的当地时钟重算日期、开关与指纹，拒绝陈旧自动领取／完成；显式重试才允许 failed/cancelled/interrupted 再次领取。配置保存通过 `save_settings(values, *, operation_id, now_utc)` 调用既有 SettingsService，原子维护 revision 和更新时间；没有头像操作。
- 所有写入由 UnitOfWork；`forget` 清内容并留下当日去重／通知墓碑，不删今天自动 ID。清理不删在途任务；失败类别使用枚举，不存上游异常原文。

- [ ] **Step 1:** 写迁移／回滚、重复领取、旧 attempt、通知受理、删除去重测试；例如重复 `claim('news:2026-10-20',...)` 只第一次返回 claim；`forget` 后当天 claim 仍为 None。
- [ ] **Step 2:** 运行 `PY -B -m unittest discover -s scripts -p test_companion_news_storage.py -v`，确认未实现失败。
- [ ] **Step 3:** 实现迁移 3 和仓储／服务／工作流；保留迁移 0→1→2；初始化后恢复其他 run_id 的 running 为 interrupted。完成报告与状态同事务，重复完成返回原结果，不重新接受通知；旧 attempt 更新影响行数为零。
- [ ] **Step 4:** 增补 `test_config_change_between_claim_and_complete`、`test_save_failure_preserves_report_for_same_attempt_retry`、`test_prune_preserves_today_and_running`。注入完成事务失败后无 completed／无通知；去掉故障后同 claim 可保存一次；过去 31 天终态删除、超 100 仅清最旧可清理项。
- [ ] **Step 5:** 运行本组与 `test_architecture.py`；验证版本 0/1/2 升至 3，真实文件旧库有可打开备份，触发迁移失败时 version 和旧数据恢复，全部通过。

### Task 3: LangGraph 来信模式与共用网络准入

**Files:** 修改 `app/modules/companion/agent.py`、`persona.py`、`api.py`、`app/integrations/companion_agent/graph.py`、`service.py`；新建 `scripts/test_companion_news_graph.py`；调整 `scripts/test_companion_react.py`、`test_companion_agent.py`。

**Interfaces:** 保留 `search(config, topic, progress)` 与 `run_search(...)`。新增 `news_system_prompt(current_time, request, limits)`、`CompanionAgentService.news(config, request: NewsRequest, progress) -> (request_id, Future)`；两入口调用同一图执行器和同一实例的锁。新增可辨识的 `AgentBusyError` 和只读 `busy`，服务取消可选 `request_id`，拒绝错误所有者取消。

- [ ] **Step 1:** 真实 LangGraph＋模型／MCP 夹具，写 `test_news_mode_uses_date_interests_and_existing_tools`、`test_search_and_news_share_admission_until_cancelled_io_ends`，断言只有现有两个工具，6/8/3/3/8/300 限额不扩大。
- [ ] **Step 2:** 运行 `PY -B -m unittest discover -s scripts -p test_companion_news_graph.py -v`，确认缺少 news 接口失败。
- [ ] **Step 3:** 抽取共同图执行入口，让业务提示词来自 companion API；没有来源不得产生成功来信，有真实来源的 warning 报告允许提交。检索时间和发布日期明确区分，不保存 reasoning／工具轮次。
- [ ] **Step 4:** 增补 `test_missing_dates_are_not_labeled_today`、`test_stale_owner_cannot_cancel_active_search`、`test_news_payload_never_contains_credentials_or_passive_profile`；固定日期夹具核对角色与日期规则，禁止将无日期资料描述成已核实当天新闻的提示约束。正文事实真实性仍列为人工限制。
- [ ] **Step 5:** 运行新组、`test_companion_react.py`、`test_companion_agent.py`、`test_companion_setup.py`，保留搜索兼容与取消准入。

### Task 4: 工作线程装配与 Qt 排期协调

**Files:** 修改 `app/bootstrap/application.py`、`features.py`、`read_models.py`、`app/ui/companion/agent_controller.py`、`controller.py`、`app/ui/main_window.py`、`main.py`；新建 `app/ui/companion/news_controller.py`、`scripts/test_companion_news_desktop.py`。

**Interfaces:**
- ApplicationWorker context 装配 news 工作流；`DesktopApplication.news_commands` 为 RemoteService。`DesktopQueries` 提供 `news_snapshot() -> MemorySnapshot`；`TABLES['companion']` 加有界任务读模型；后台 `_refresh` 对该表使用有界排序查询，不能长期 SELECT 全部历史。
- `CompanionNewsController(companion, agent_controller, commands, queries, *, now_local, now_utc)`；`tick()`、`run_now()`、`retry(task_id)`、`retry_save()`、`sync_settings()`、`pause()`、`resume()`、`shutdown()`。复用 agent_controller.service、TaskBridge 与卡片，不创建第二个网络服务；保存结果在 Presenter 中保留至成功或明确丢弃。
- 默认关闭也可构造；QTimer 30,000ms，隐藏不暂停排期，只暂停视觉提示；未完成的领取／保存各最多一项。只有纯规则到期才提交 claim，无到期不写库。
- 启动前忙碌延后；领取后准入竞争用 release_unstarted 还原 waiting，沿用 ID，不能按上游失败处理。真正开始后失败不自动重试。

- [ ] **Step 1:** 使用真实 DesktopApplication＋Qt＋阻塞网络夹具写 `test_no_due_tick_performs_no_sql_or_network`、`test_fifty_ticks_claim_one_daily_job`、`test_committed_models_precede_ui_notice`；先确认红灯。
- [ ] **Step 2:** 装配 context／读模型／命令、配置保存版本和 Presenter 状态；跨线程只发布冻结类型。主窗接收 companion 主题，profile 变更同步配置；关窗驻留保留排期。
- [ ] **Step 3:** 写 `test_busy_race_releases_unstarted_same_id`、`test_pending_save_retry_does_not_call_model_again`、`test_config_change_discards_late_auto_result`、`test_cancel_old_attempt_does_not_cancel_search`；断言模型调用数分别为 1、1、旧任务无通知、当前搜索仍有效。
- [ ] **Step 4:** 连接真实退出与更新暂停／恢复：停止定时和结果接收后再关闭数据库准入；更新准备失败恢复排期但不重跑旧网络。写 `test_update_pause_resume_preserves_pending_save`、`test_restart_marks_running_interrupted_without_network`；默认完全无网络。
- [ ] **Step 5:** 运行新组、`test_desktop_architecture.py`、`test_updates.py`、`check_architecture.py`；SQLite trace 仅有单个 ApplicationWorker thread ID，全部通过。

### Task 5: 来信设置、轮盘与已提交通知

**Files:** 新建 `app/ui/companion/news_settings.py`、`scripts/test_companion_news_ui.py`；修改 `agent_settings.py`、`agent_widgets.py`、`agent_controller.py`、`controller.py`、`app/ui/tray.py`；调整 `scripts/test_companion_agent_ui.py`、`preview_companion_agent.py`。

**Interfaces:** `NewsSettingsPanel(config, snapshot)` 提供 `values()`、`set_snapshot(snapshot)`、`run_requested/retry_requested/memory_requested` 信号。AgentSettingsDialog 新增「定时来信」「记忆」入口，`values()` 合并新闻键；保存走任务 4 的异步命令，取消不写入。轮盘新增 `news_requested`，占卜继续禁用。

- [ ] **Step 1:** 写默认值、安静时段错误、取消草稿、保存失败保留、主题同步测试；写轮盘点击不调用网络的断言，先运行确认失败。
- [ ] **Step 2:** 用原有 SettingsSheet／AgentColors 实现非对称设置区，时间用原生 QTimeEdit，兴趣多行输入；「现在汇报」明确是联网动作，取消连接测试不改变排期。
- [ ] **Step 3:** 通知资格同时检查安静、可见、练习与搜索卡占用；满足后先异步 accept_notice，提交成功才调用卡片 show_report 和桌宠反馈。隐藏／练习恢复至多呈现最新一封；不抢焦点、不自动打开详情。
- [ ] **Step 4:** 写 `test_hidden_or_practicing_defers_notice`、`test_search_card_not_overwritten`、`test_notice_accept_failure_does_not_show_card`、`test_restart_does_not_repeat_accepted_notice`、`test_news_button_opens_latest_or_settings_without_network`。
- [ ] **Step 5:** 运行新组与 `test_companion_agent_ui.py`、`test_companion_ui.py`、`test_companion_integration.py`；隔离预览截取宽／窄配置、短卡、详情与减弱动态状态，人工读图检查无黑色底板和裁切。

### Task 6: 我的记忆／开发者双视角

**Files:** 新建 `app/ui/companion/memory_page.py`、`memory_presenter.py`、`app/integrations/development_index.py`、`scripts/test_companion_memory.py`、`test_companion_memory_ui.py`；修改 `app/bootstrap/features.py`、`agent_settings.py`、`news_controller.py`。

**Interfaces:**
- `MemoryPresenter(queries, news_commands)`：`snapshot() -> MemorySnapshot`、`forget(task_id, operation_id) -> Future`、`save_interests(text, operation_id) -> Future`；用户／开发者两页选择同一 stable ID。
- `MemoryPage(presenter, development_index)`，共用只读 snapshot；普通卡片显示本人填写／主动来信、更新时间和真实提交状态。删除明确确认，取消不写，失败不提前移除；删除兴趣等同保存关闭的空画像，不擅自重启排期。
- `DevelopmentIndexService.snapshot(object_refs) -> Future[CodeIndexSnapshot]` 仅从非冻结源码根读取有界 `aoci*.txt` 与 `.aoci/baseline.json`，单文件不超过 2MiB，选定对象为固定代码入口。baseline 只用受支持版本的 `files[白名单路径].sha256` 对照所选源码摘要，不展示其他对象或本机配置。纯文本 FRAS 只供展示，不执行命令、不推导新语义、不读用户数据库。未调用 AOCI 时标「本地索引快照，治理状态未核验」；缺失／格式不支持／源码摘要变化如实显示不可用、未核验或过期，不冒充 aligned。
- 代码入口由固定白名单确定：companion API、news_service、repository、news_controller、memory_presenter。源码模式打开已核对的本仓库文件并显示定位；冻结模式显示模块名及构建提交对应 GitHub 链接，没有源码提交时提示该版本源码入口不可用。索引文本不得提供任意路径／URL。

- [ ] **Step 1:** 写 `test_both_views_share_record_identity`、`test_empty_or_memory_only_report_is_not_saved`、`test_forget_today_keeps_auto_dedup`、`test_failed_forget_preserves_card`；先运行确认新接口缺失失败。
- [ ] **Step 2:** 实现同一快照的两种展示、兴趣修改和显式删除；保存中／失败状态由异步命令产生，成功时间来自持久层。正常 UI 不展示 Key、完整模型配置、私有推理或用户数据绝对路径。
- [ ] **Step 3:** 写 `test_missing_or_stale_aoci_does_not_block_memories`、`test_packaged_without_sources_uses_module_fallback`、`test_index_cannot_escape_code_allowlist`、`test_source_html_and_long_chinese_are_plain_text`；再实现可选索引读取与代码入口。读取工作放后台，UI 只接收脱敏展示类型。
- [ ] **Step 4:** 运行两新组与真实桌面组；隔离截图验证 560px 宽配置、长中文来源、空态、失败态、两标签焦点顺序及统一主题；真实 IME／DPI／多屏未验项单列。

### Task 7: 兼容、冻结自检、版本与最终验证

**Files:** 修改 `app/__init__.py`、`README.md`、`CHANGELOG.md`、`docs/architecture.md`、`docs/companion-agent.md`、`docs/project-state.md`、`docs/validation.md`、`app/integrations/companion_agent/probe.py`、`scripts/build_release.py`；按实际变更更新 AOCI。

**Interfaces:** 保留 `--companion-agent-selfcheck`；扩展其无网络夹具验证来信模式与日期规则。构建模块检查纳入已实现的新模块；历史源码没有新文件时不强制要求，保持旧版构建兼容。只调整冻结验证清单，本任务不构建或发布安装包。

- [ ] **Step 1:** 写旧版源码／新版本模块识别、来信 selfcheck 回归；运行红灯后补实现与中文说明。应用版本设置 0.9.7，schema 保持已实现的 3；占卜仍标第三期未开放。
- [ ] **Step 2:** 运行 `PY -B scripts/check_architecture.py`、`PY -B scripts/check_comments.py`、`PY -B -m unittest discover -s scripts -p 'test_*.py' -v`、`PY -B scripts/selftest.py`、`PY main.py --companion-agent-selfcheck`。确认无失败，记录实际用例数、环境和既有失败，不引用历史 342 项冒充本轮结果。
- [ ] **Step 3:** 自查所有变更的线程、事务、attempt CAS、准入、脱敏和注释；按执行技能安排最终独立 review，处理实际发现后重跑相应检查。若没有获得多智能体执行方式，不提前启动子智能体。
- [ ] **Step 4:** 更新文档中的实际状态／入口、截图证据与未验证项，检查本地链接和 `git diff --check`；受管理文件稳定后一次 Maintain，按签发批次作者化并完成 Verify→Check→Guide，不能强制重扫或手工清基线。
- [ ] **Step 5:** 给出工作区交付：定时来信、重启历史与两种记忆视角的入口和验证结果；注明未发布、未用真实模型／公开搜索验收、未实际迁移用户数据、未做冻结包／安装／IME／DPI 人工验收。

## 自审与计划交接

实施接续：任务 1—7 产品代码与审查修正已实现，最终全量 450 项通过；实际证据以 [validation.md](../../validation.md) 为准，索引按当前合同收尾维护。下列步骤保留原始验收清单，不凭计划文本冒充执行证据。未提交、推送或发布。

已将两份设计的规则、迁移、跨线程、通知语义、记忆来源与删除、可选 AOCI、版本与验证映射至任务 1—7；五项 Review Focus 均有对应测试。自动删除去重墓碑、旧 attempt、保存重试和更新退出为必须验收项，不用普通成功路径替代。

已选择 **Native：当前会话由主智能体顺序实现**。这些任务共享同一组 claim／attempt／只读模型接口，顺序执行便于保持协议一致；不为每个小任务另开实现和审查上下文。用户已认可计划与此执行方式，直接按任务继续，不在任务之间重复询问是否继续。
