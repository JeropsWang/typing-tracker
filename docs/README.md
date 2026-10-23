# Sariana 维护文档

首次维护按以下顺序阅读：

1. [项目 README](../README.md)：产品行为、启动方式、数据位置和发布方式。
2. [架构文档](architecture.md)：模块归属、线程、事务、恢复和新增功能的接入点。
3. [AI 协作指南](agent.md)：如何给 AI 工具交代任务、检查方案、验证和交付。

仓库根目录的 [AGENTS.md](../AGENTS.md) 是 AI 维护入口。`docs/agent.md` 是完整说明，不应假设任意工具会自动读取这个文件；开始任务时明确要求工具阅读它。

跨会话接手读取 [项目接续状态](project-state.md)，其中链接当前任务的设计／计划和验证入口。0.9.7 定时来信及双视角记忆见 [定时来信设计](superpowers/specs/2026-10-20-companion-news-design.md) 和 [统一实施计划](superpowers/plans/2026-10-20-companion-news-memory.md)；实现、发布及未验证范围以实际源码和验证记录为准。

[AOCI 试用记录](aoci.md) 说明开发侧 MCP 接入、包核验、语义索引、增量维护及本机查看面板。开发者也可直接阅读 [语义索引](../aoci.code.txt)；桌宠应用内的「我的记忆／开发者」页面见 [已确认设计](superpowers/specs/2026-10-20-memory-views-design.md)。

英语交互参考与 REA 证据见 [english-research.md](english-research.md)；GitHub 检查、下载校验与更新退出流程见 [updates.md](updates.md)。

代码是实现事实的来源。修改接口、模块边界、迁移或验证命令时，同步更新相关文档。验证记录见 [validation.md](validation.md)，记录结果和未验证项，不把未运行的检查写成通过。

注释规范与检查命令见 [AI 协作指南](agent.md#代码注释与维护说明)；[注释覆盖检查](../scripts/check_comments.py) 只读扫描全部自有 Python 模块、类与函数，内容准确性仍需结合代码审核。

桌宠智能体的三期计划、模型/搜索配置、LangGraph 边界和本机模型验证见 [companion-agent.md](companion-agent.md)。
已下载 Pi 源码的位置、固定版本、阅读顺序与本项目的架构对照见 [Pi 源码导读](pi-agent-study.md)。
桌宠轮盘、手信卡片与配置页的公开网页参考及 REA 证据见 [companion-agent-design.md](companion-agent-design.md)。
