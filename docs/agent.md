# 使用 AI 工具维护 Sariana

这份指南适用于人和 AI 协作者。目标是先找到业务归属和正确入口，再做可验证的修改。架构说明见 [architecture.md](architecture.md)，产品行为见 [README](../README.md)。

## 开始一个任务

让工具先读取根目录 `AGENTS.md`、这份文档、架构文档和目标模块 `api.py`。不要把旧总结当成当前代码事实；先检查分支、工作区和调用链：

```powershell
git branch --show-current
git status --short
rg --files app scripts docs
rg -n '相关类名|相关方法|业务关键词' app scripts
```

在当前指定分支工作。已有修改先辨认归属，不执行清理、强制重置或覆盖他人代码。依赖、缓存、用户数据库、预览和构建产物不提交。

给 AI 的任务至少说明：触发方式、预期结果、影响范围、需要保留的行为和验收场景。能够由代码查明的事实让工具自行查找；确实影响产品行为的选择再讨论。

推荐提示词：

> 请先阅读 AGENTS.md、docs/agent.md 和 docs/architecture.md，再检查当前分支、工作区与目标调用链。任务是：[具体问题或功能]。复现步骤：[步骤]。预期行为：[结果]。保留：[评分、奖励、日切、隐私或界面约束]。先说明模块归属与需要修改的接口，然后实现、运行相关回归，并报告改动、测试证据和未验证项。不要改用户真实数据目录，不要自行推送或发布。

排查故障时补充异常日志、发生时间、应用版本和脱敏数据形状；无需提供 API Key、被动键盘输入正文或整份私人数据库。

## 按改动找到入口

| 任务 | 首先阅读 | 重点验证 |
| --- | --- | --- |
| 统计丢失、重启、日切 | tracking API/domain、workflows/checkpoint、storage/db | 保存失败、同分钟续写、跨日、确认丢失 |
| 经验、打卡、道具、成就 | growth API、对应服务、growth 仓储 | 原子回滚、日上限、重复领取、数量消费 |
| 普通训练、纪录、键盘侠 | practice API、ui/presenters、训练页面 | 稳定操作 ID、保存失败重试、不提前庆祝 |
| 英语拼写、复习、造句 | english API、bootstrap/features、英语页面 | 首次/纠正/复测分离、排期原子性、日切、取消结果、单词评分 |
| AI 协议、用量、并发 | integrations/ai、ui/tasks、请求包装类 | 配置快照、共享 gate、迟到结果、保存重试不再计费 |
| 设置、头像 | profile API、bootstrap/features、settings_dialog | 草稿取消、提交失败、头像补偿、异步关闭 |
| 小伙伴、作品包 | companion API、ActivityProvider、ui/companion | 公共活动状态、拖动、模式、素材校验与动效 |
| 桌宠智能体 | companion API、integrations/companion_agent、ui/companion/agent_* | 真实图执行、配置隔离、取消与迟到结果、来源、流式思考过滤 |
| 报表与性能 | reporting API、bootstrap/read_models、reports | 缓存失效、隐藏后刷新、格子复用、无 UI SQL |
| 旧库升级和发布 | storage/db、build_release、工作流与安装脚本 | 版本迁移、迁移备份、包内代码/素材、安装升级 |
| 自动更新 | integrations/updates、ui/updates、bootstrap/application、main | 校验/取消、最终保存失败重试、安装交接授权、真实 Windows 安装 |

## 实现时遵守的边界

- 新业务代码使用 `app/modules/<业务>/api.py`。旧 services/english/companion 转发入口用于兼容，不是新功能落点。
- UI 持有 Presenter、只读查询与异步命令能力；生产路径不用同步 DataSession。不要复制预览夹具的直接 SQL 装配到页面。
- 数据库连接只属于 ApplicationWorker。主线程不等待未完成的 Future，后台线程不访问 QWidget。
- 纯规则不依赖 Qt、数据库或网络。计时/日切使用可注入时钟，不在各页面复制日期口径。
- 一个完整写操作由 UnitOfWork 决定提交；禁止仓储内部 commit、跨模块内部仓储访问，以及事务内网络请求。
- 保存重试沿用原操作 ID/请求 ID。成功提交之前不宣布成绩完成、不发彩带、不驱动小伙伴奖励反应。
- 统计只在提交后确认版本，失败不清除脏数据。实时展示读内存，写入资格在事务内检查。
- 保留三种准确率的差异、tw 计数、凌晨 4 点应用日、键盘侠 15 秒、英语不发额外经验等现有规则。
- 保持本机离线、无额外服务的运行约束。不要为了组织代码引入 Redis、ORM、DI 框架或新 UI 技术。

遇到边界违规先调整服务接口/用例；不要通过关闭线程检查、吞异常、复制 SQL 或额外轮询绕过问题。确实需要修改架构时，同步更新架构文档和导入检查。

## 代码注释与维护说明

所有新增或修改的代码必须补充清晰的中文功能说明，作为交付要求执行。维护者应能从注释直接知道代码负责什么、从哪里调用及有哪些边界，不应依靠重新推演实现来猜测功能。

- 模块说明写清业务用途与所在层；类说明写清职责、持有的状态与线程归属。
- 每个新增或修改的函数、方法都要有功能说明，Python 优先使用 docstring；私有辅助函数、嵌套函数、UI 槽函数和脚本入口同样适用。简单函数可用一句话说明，复杂函数说明主要输入、返回结果、异常或副作用；涉及单位、编号、限额或特殊约定时写明其含义。
- 关键流程、复杂分支、状态转换、异步回调、事务、取消/迟到结果、隐私与安全检查、兼容处理必须在对应代码旁说明原因和需要守住的约束。注释解释设计意图，避免只把赋值、循环等语法重复一遍。
- 修改功能时同步更新注释，删除过时说明；修改已有函数时补齐其缺失的功能说明。用户文案、模型提示词和独立架构文档不能代替函数注释。
- 测试与检查脚本说明验证场景和隔离条件。交付前检查本次新增/修改的模块、类、函数与关键分支是否已注释，并核对说明与实际代码一致；不能把补注释变成无关的全仓格式重写。

整个项目的历史代码也遵守此规范。运行 `python -B scripts/check_comments.py` 检查 `app/`、`scripts/` 和 `main.py` 的模块、类、函数（含私有方法与嵌套回调）是否有非空 docstring；`--json` 可输出覆盖明细。检查不导入应用、不请求网络、不操作数据库，不扫描 `.local` 中的第三方 Pi 源码或依赖。它只检查说明存在性，维护者仍须核对内容、关键分支及 PowerShell/SQL/安装配置的说明是否准确。

## 环境与验证命令

Windows 源码支持 Python 3.10+；发布与 CI 使用 Python 3.13 和 `requirements-release.txt` 中锁定的依赖。架构重构与依赖升级分别验证。

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-release.txt
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
.venv\Scripts\python.exe -B scripts/check_architecture.py
.venv\Scripts\python.exe -B scripts/check_comments.py
.venv\Scripts\python.exe -B -m unittest discover -s scripts -p 'test_architecture.py' -v
.venv\Scripts\python.exe -B -m unittest discover -s scripts -p 'test_desktop_architecture.py' -v
.venv\Scripts\python.exe -B -m unittest discover -s scripts -p 'test_*.py' -v
.venv\Scripts\python.exe -B scripts/selftest.py
```

先运行改动相关测试，再进行必要的完整回归；没有新改动或失败原因时不反复重跑全量测试。文档改动检查链接、路径和命令，不为了文案新增行为测试。

测试和预览使用临时数据或 `.local/` 中的隔离目录；不指向 `%APPDATA%\TypingTracker`。真实 AI 请求会产生费用，自动化使用模拟响应或本地测试 HTTP 服务。全局输入钩子的人工验证与普通离屏 UI 测试分开进行。

人工运行前从本进程清除离屏平台设置，再指定隔离数据目录：

```powershell
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
.venv\Scripts\python.exe main.py --data-dir .local/manual-data
```

界面改动检查中文输入法组字、禁粘贴、1440×1024 主窗口、820×640 设置窗口、DPI、托盘统计、动态效果和小伙伴两种模式。不能用离屏测试代替真实 IME 与多显示器体验验证；未做的项目在交付中写明。

发布构建需要 Inno Setup 6。参考 `scripts/build_release.py --help` 和 README，使用明确源码版本生成冻结包。`scripts/test_installer.ps1` 涉及实际安装和卸载，并拒绝已经安装同产品的环境；在干净 Windows 测试机运行。构建成功与安装升级通过是两个结果，不合并表述。

发布 0.9.5 起可先创建草稿，再手动运行 Windows Release 工作流，设置标签与 `publish_draft=true`；只有构建、安装与旧版本升级检查通过并上传附件后才公开。匿名在线更新检查用 `scripts/verify_release_updates.py`，缓存与报告放隔离目录；`--exe` 仅指向已验证的本仓库发布包，工具不会运行安装器。

## 数据迁移与缓存变更

新增表/列时先确定数据归属，再新增版本迁移并增加旧库样本测试。迁移前在线备份，失败原子回滚；不用复制正在使用的裸 `app.db` 文件替代 Backup API。不要改旧版本迁移来假装已升级用户会自动补列。

新查询先确认现有展示读模型是否满足。需要新数据时更新工作线程的加载/失效主题和查询接口，避免页面重新查询数据库。缓存返回可独立使用的数据，写操作不能根据展示缓存决定余额或资格。

涉及统计恢复、奖励、扣券或异步状态时，用中途失败、重复提交、重启和取消验证结果；不要只测试成功路径。

性能样本可独立复现：

```powershell
.venv\Scripts\python.exe -B scripts/benchmark_architecture.py --samples 10 --output .local/performance.json
```

该脚本生成 365 条日报与 43,200 条分钟记录，使用临时数据库，测量启动、检查点、摘要和时段查询。它不测实际绘制帧率或真实输入法延迟；比较版本时固定机器、依赖与样本。

## 交付和文档更新

交付说明应包含：具体行为变化、接口/迁移影响、运行的命令与结果、既有失败、人工或发布验证限制。说明代码处于工作区还是已提交；只有明确要求时才提交、推送、创建正式发布或上传附件。

修改边界、目录、线程、事务、恢复、构建或验证命令时更新 [architecture.md](architecture.md)；修改维护流程时更新这份指南。运行记录写入 [validation.md](validation.md)，注明样本与环境，不把本机性能数值当成所有机器的保证。

英语交互参考见 [english-research.md](english-research.md)，更新机制见 [updates.md](updates.md)。更新回归使用模拟 GitHub 响应和隔离数据，不启动真实安装包；干净 Windows 环境另测安装向导、钩子恢复和升级后数据保留。

桌宠智能体迭代、配置与验证见 [companion-agent.md](companion-agent.md)。安装新增 LangGraph 依赖后运行 `test_companion_agent*.py`、小伙伴回归和真实桌面工作线程测试。真实本机模型验证需用户授权；默认验证工具用 HTTP 搜索夹具，不能据此宣称真实搜索服务连通。打包需收集 LangGraph 子模块及依赖元数据，并运行冻结程序 `--companion-agent-selfcheck`。

桌宠 ReAct/MCP 工具层变化同时运行 `test_companion_react.py`，覆盖自主补搜、错误观察、稳定引用、来源读取白名单、截断调用、次数/上下文/截止时间和取消。默认角色在 companion 纯规则层维护，新增纯文件列入架构检查。Pi 固定版本源码位置与对照见 [pi-agent-study.md](pi-agent-study.md)；参考目录不进入发布。不要把 MCP 工具子集说成已支持任意外部服务器，也不要把短连接测试通过说成已验证原生工具调用。

模型/搜索连接测试见 `test_companion_setup.py`；公开 RSS 的错误回退、来源限额、取消和 XML 过滤见 `test_companion_agent.py`；Edge DOM、原文读取限额、内网拒绝与所属进程清理见 `test_companion_edge.py`。自动化使用模拟响应；真实联网上游验证通过 `verify_companion_agent_local.py --public-search`，只使用隔离数据及用户授权的本地模型。测试不得保存草稿或输出 Key；取消后保持后台准入直至任务结束。已有 SearXNG 仅连接，禁止操作外部容器。
