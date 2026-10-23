# AOCI 开发认知试用

2026-10-20 用户授权在 Sariana 项目试用 [AOCI-CODE](https://github.com/aoci-spec/aoci-code)。本次只接入开发工具，不将其加入桌宠运行依赖、不修改用户真实数据库，也没有提交或发布。

## 安装与边界

- 固定官方候选版 `v0.1.0-rc21`，源码提交 `cfa8e93ca9fe546a375f48b41b3d4766ed98b013`。
- 稳定可执行路径：`D:/Sariana-typing-tracker/typing-tracker/.local/tools/aoci/0.1.0-rc21/bin/aoci.exe`。它属于本机工具，不能依赖该路径在别人的机器上存在。
- Windows amd64 ZIP SHA-256：`d7a34e5f419b8f8be56739e9b4e9a772019950aecd159539f6a94c9d6b499665`；解压程序 SHA-256：`b303f9caae997ab851dc2ca98e148c088c2ae192cca85de760941b61d617eeb5`。
- 已比对下载的 SHA256SUMS、GitHub 附件摘要与本地 ZIP；通过 GitHub CLI 对所选 ZIP 的 provenance 核验，限定官方仓库、release.yml、标签、源码提交与非自托管构建。
- 没有执行官方完整供应链核验的所有步骤；没有 Cosign 校验 SHA256SUMS 签名，也没有下载其余平台的全部附件。不能将所选包的核验写成完整 16 附件验证。
- 项目 `.codex/config.toml` 配置 stdio MCP 与稳定绝对路径，已加入 Git 忽略。不改全局 Codex 配置、不安装生命周期 Hook，也不配置额外模型端点或密钥。
- 原 AGENTS.md 的字节内容保留，追加官方托管区块。安装前文件备份位于 `.local/aoci-trial/backups/before-project-init/`。
- 初始化生成的全仓 LF 规则已收窄到 AOCI 资产，不执行全仓源码换行重写。

初始化和后续 MCP 使用项目内 `.local/aoci-trial/tmp` 作为 TEMP/TMP，避免受限 Windows 临时目录的原子重命名失败。首次隔离预演确实遇到该权限错误，切换临时目录后通过；未为绕过错误关闭治理检查。

## 扫描与建立索引是两个阶段

本节数量及核验记录对应首次索引建立阶段；后续设计／计划新增文件继续增量维护，当前条目数量以实时 Verify 为准。

初始范围为 `full`，包含自有业务代码、测试、文档、部署与构建配置。试扫曾将 `.deps` 第三方文件列入目标，已在建立正式基线前设置显式根目录排除：`.deps`、`.dl`、`.local`、`.superpowers`、构建、依赖、缓存与预览目录。不索引本地 Pi 副本、模型配置或用户数据库。

`scan` 只建立文件清单与摘要，不代表已理解文件。初始化时 `aoci.txt`、`aoci.meta.txt`、`aoci.code.txt` 仅为骨架；随后宿主模型按实时 Guide 阅读源码和相关证据，通过 MCP 完整候选批次建立了 331 条语义索引。未用路径／AST 模板生成职责或约束。

实际扫描建立 348 个文件指纹，估算 330 个语义创作目标；Doctor 配置诊断通过。独立短时进程已成功执行 MCP `initialize` 与 `tools/list`，确认版本和九个工具，进程随后正常关闭；这证明二进制的 stdio 接口可用，不代表本 Codex 会话已经加载服务器。检查记录位于 `.local/aoci-trial/setup-verification.json`。

实测限制：`full` 模式仍把已被 Git 忽略的 `.codex/config.toml` 列为索引目标，不能把 Git 忽略等同于 AOCI 排除。当前该文件只有工具路径、仓库路径和 TEMP/TMP，不含 Key。曾预览额外排除该文件的 Scope Change，工具要求真实人工审批，正式写入未开始；该可选提议已撤回，未伪造审批或强制重扫。当前 desired/active policy 一致。以后若要缩减正式范围，遵守工具审批流程。

最终 Code 范围为 346 个源码／资源对象，其中 331 个可创作语义目标全部建立条目，另 15 个二进制或超大素材由工具明确技术跳过。新增记忆页设计已纳入；数据库表认知卷未配置，不代表已建立用户数据库索引。

用户重启后，2026-10-20 当前会话已实际加载九个 AOCI MCP 工具。`aoci_rules` 与 Overview 确认运行版本 0.1.0-rc21 和正确项目根。补齐索引后顺序执行 `verify --json`、`check --json`、`index agent guide --agent codex --json`，均退出 0，结果为 aligned／ok／next_action=none；missing、stale、unbaselined、orphan、Scope 债务和 Recovery 均为零。通过受绑定的认知优化批次校正 8 个规模标签、两处关系路径和两处契约名称；后续验证规模不匹配为零，关系目标均存在。

中间态 314 条的完整 Overview 分 4 块交付，Host 确认后 Challenge 10/10 通过；该收据只绑定当时索引，不等于已经重读最终 331 条。索引对齐与模型当前完整认知可靠性是两个事实，后续会话按 AGENTS 中的规则重新建立认知。

同日本机只读浏览器面板已启动并通过 HTTP 200 检查，绑定 `127.0.0.1:53468`，已在浏览器打开。面板端口和访问令牌属于本机运行状态，后续用 `aoci ui --detach --json` 取得当前地址；不把访问令牌写入仓库。

接续时可直接发送：

> 先确认当前项目 AOCI MCP 已加载，按 AGENTS 读取当前完整认知；再核对工作区和 docs/project-state.md，继续 0.9.7。索引已建立，不要重新 bootstrap 或强制重扫；源码稳定后按当前 Guide 增量维护。

可用于本机诊断的命令：

```powershell
$AociTool = 'D:/Sariana-typing-tracker/typing-tracker/.local/tools/aoci/0.1.0-rc21/bin/aoci.exe'
$env:TEMP = 'D:/Sariana-typing-tracker/typing-tracker/.local/aoci-trial/tmp'
$env:TMP = $env:TEMP
& $AociTool --repo 'D:/Sariana-typing-tracker/typing-tracker' doctor
& $AociTool --repo 'D:/Sariana-typing-tracker/typing-tracker' status --json
& $AociTool --repo 'D:/Sariana-typing-tracker/typing-tracker' verify --json
& $AociTool --repo 'D:/Sariana-typing-tracker/typing-tracker' check --json
& $AociTool --repo 'D:/Sariana-typing-tracker/typing-tracker' index agent guide --agent codex --json
& $AociTool --repo 'D:/Sariana-typing-tracker/typing-tracker' ui --detach --json
```

不使用 `scan --force` 清除漂移，也不为消除缺失条目提示手动篡改 baseline。索引完成后的维护按当前 MCP 合同执行；仍须运行实际产品测试，AOCI 对齐不能替代行为验证。

## 与现有项目记忆的分工

- AGENTS.md 与 docs/agent.md：维护规则和协作入口，用户明确指示优先。
- AOCI：与源码摘要绑定的文件职责、关系、契约和关键约束；入口为 [根清单](../aoci.txt)、[语义索引](../aoci.code.txt) 与本机只读浏览器面板。搬到其他机器需要重新安装并配置本机 MCP 路径。
- docs/project-state.md：当前任务、阶段、已确认／待审事项和下一步。
- 设计／实施文档：产品决策与执行步骤；docs/validation.md 保存实际验证证据。

## 桌宠智能体可借鉴的方向

用户提出小 Agent 项目也可考虑此方案。适合借鉴的是：显式且可审查的长期记忆、记录来源和更新时间、更新后识别过期信息、按用途区分记忆与任务状态。开发仓库索引与桌宠个人记忆是不同数据域，不应直接共用。

桌宠后续可由 companion 公共 API 暴露受控记忆读取／更正能力，LangGraph 在需要时读取明确授权的兴趣与偏好，写入通过工作线程和 UnitOfWork 校验提交。网页内容与模型生成内容不能自行升级为用户偏好，用户应能查看、更正和删除；不记录被动键盘输入或私有推理。

应用内「我的记忆／开发者」两个视角已按 [记忆页设计](superpowers/specs/2026-10-20-memory-views-design.md) 与 [统一实施计划](superpowers/plans/2026-10-20-companion-news-memory.md) 接入 0.9.7 工作区。用户记忆来自 schema 3 的 companion_news_tasks 与显式兴趣设置；开发者展示同一记录，并可选读取固定代码入口的 AOCI 原文和基线摘要。产品不依赖运行时 MCP 或 Go；本地索引只标快照／未核验／过期，不能据摘要匹配宣称治理 aligned。开发侧正式认知仍由 MCP 的维护和 Verify→Check→Guide 管理，二者不共享私人数据。
