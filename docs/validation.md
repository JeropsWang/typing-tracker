# dev 架构升级验证记录

日期：2026-10-13（Asia/Shanghai）。应用代码基于 dev 的 `17c0bce`，另含本次文档、构建验证器、性能脚本及测试入口收尾修改。本文记录本机实际验证，不代表已推送 CI 或正式发布。

## 环境与隔离

- Windows x64、Python 3.13.7、SQLite 3.50.4。
- 使用 `requirements-release.txt` 锁定的依赖，包括 PySide6 6.11.2、pyqtgraph 0.14.0、PyInstaller 6.22.3。
- 本机无可用的系统 Python 安装，因此使用项目 `.local/` 中的官方便携 Python，依赖位于忽略目录 `.deps/`；维护者正常使用 `.venv/` 即可。
- UI 回归使用离屏平台和隔离数据库，AI 使用模拟响应/本地测试服务；未请求真实模型、未修改真实用户数据库。
- 设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，避免 Windows 中文子进程输出以本机默认编码产生解码失败。

## 结果

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| 全量 unittest 回归 | 225 项通过，约 499 秒 | 原有产品测试 + 25 项架构测试 + 6 项真实桌面工作线程测试 |
| 应用 selftest | 103 项通过 | 计数、评分、存储、奖励及输入适配的自检 |
| 架构导入检查 | 通过 | UI 存储隔离、纯规则依赖、跨模块公开 API |
| 导入边界新增专项 | 5 项通过 | 数据库子模块/别名导入、内部仓储导入、公开 API、纯规则和连接访问 |
| 架构测试入口收尾 | 25 项通过 | 临时目录初始化不依赖此前运行 UI 测试 |
| 桌面工作线程测试入口收尾 | 6 项通过 | 异步确认、保存重试、请求取消、缓存读取、错误反馈 |
| 冻结 EXE 构建与验证 | 通过 | PyInstaller 构建、`--help` 启动、137 个源码模块、66 个运行资源逐项一致性 |
| 文档引用和 Git 空白检查 | 通过 | 本次文档的相对链接和引用路径，以及 `git diff --check` |

全量回归之后只调整维护文档、测试临时目录初始化、导入检查及构建验证器；对新增/修改检查运行了对应专项。225 项是该次全量运行数量，新增导入专项单独记录，避免把没有执行的全量结果写成 230 项。

构建验证器根据目标源码布局选择必需模块：新架构验证 bootstrap、tracking、growth 和 integrations；旧标签保留对旧 AI 服务入口的验证，以兼容现有历史版本构建流程。本次实际构建的是当前 dev 源码，未重新构建所有历史标签。

本地冻结包位于忽略目录 `.local/package-check-4cb47851/payload/Sariana.exe`。SHA-256：

```text
062e4aa09626206f1a95a521ba9720101b37a0a66340d6433fa147ad10e93316
```

它是本地验证产物，未上传发布；新克隆中没有该文件。源码/资源比对通过 `scripts/build_release.py` 的 `build_executable()` 和 `verify_executable()` 执行，不等同于安装包或实际桌面操作验证。

## 性能样本

复现入口：`scripts/benchmark_architecture.py --samples 10 --output .local/performance.json`。脚本建立临时数据库，含 365 条日报、30 天共 43,200 条分钟记录；不创建窗口，使用空成就定义，测量应用工作线程和展示查询路径。

| 指标 | 本机测量 |
| --- | --- |
| 应用装配/读模型初始化 | 117.7 ms |
| 10 次变化检查点保存中位值 | 112.9 ms |
| 检查点保存最大值 | 121.2 ms |
| 快照 + 设置 + 经验摘要读取平均值（1,000 次） | 0.0046 ms |
| 30 天时段查询 | 0.66 ms |

数值来自本机的一次样本，不是跨机器的性能承诺，也没有测量真实绘制帧率、全部成就评估或输入法延迟。2 秒表示正常情况下的保存尝试间隔；存储故障时未保存窗口可能更长。

## 未完成的发布/人工验证

- 本机 PATH 与常用安装位置未找到 Inno Setup 编译器，本次未构建安装包，也未执行实际安装、卸载和跨版本安装升级。现有发布工作流在干净 Windows 环境提供对应验证，需在发布时确认运行结果。
- 未完成真实中文输入法、多显示器和 DPI 的人工体验验证；离屏 UI 回归与输入适配自检已执行，不能替代这些检查。
- 未在 Python 3.10 上运行本次回归；3.10+ 为源码兼容目标，实际验证环境为 3.13.7。

维护和复现命令见 [agent.md](agent.md)，架构与迁移约束见 [architecture.md](architecture.md)。未来验证追加结果时保留版本、环境、样本及未验证项，不能只把本次日期改成新日期。


## 2026-10-13 英语学习与 GitHub 更新

在 `dev` 工作区实现，未提交、推送或发布。使用 Python 3.13.7、PySide6 6.11.2，`QT_QPA_PLATFORM=offscreen`。所有数据库、预览与下载测试均为隔离数据；未修改用户真实数据。REA 的网站动作与 Evidence ID 见 [英语研究](english-research.md)。

| 检查 | 实际结果 | 范围 |
| --- | --- | --- |
| 架构导入检查 | 通过 | 新增复习纯规则也加入检查集合 |
| 英语、真实桌面工作线程、更新联合专项 | 53/53 通过 | `test_english_learning`、`test_english_training`、`test_english_ui`、`test_desktop_architecture`、当时 16 项 `test_updates` |
| 最终更新专项 | 17/17 通过 | 增补配置写入失败后仍限制自动检查频率；校验、取消、最终保存失败重试、安装授权与关闭失败 |
| 材料保存互斥及旧材料跟打补测 | 2/2 通过 | 不允许在生成材料等待保存时开始另一轮；旧材料可正常练习 |
| 字号与纠正/复测补测 | 1/1 通过 | 三档字号持久化、首次成绩与复测分离 |
| 空输入与 Enter 提交补测 | 1/1 通过 | 空作答不进入保存锁定，后续输入与提交仍可用 |
| 全量回归 | 257 项，255 通过，2 项 error | 运行时的完整测试集合；随后只对新调整补测，没有宣称重新跑过最终全量 |
| 自检 | 103 项通过 | 本机模拟 HTTP、输入适配与钩子安装/卸载冒烟，没有真实 AI 请求或按键注入 |
| 文档本地链接、Git 空白检查 | 通过 | README、维护指南、架构、研究与更新说明 |
| 离屏视觉检查 | 已完成 | 1440×1024 主窗口的大/特大英语、900×640 独立英语页的上下布局、820×640 更新设置页 |

全量命令：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
# 在隔离临时目录配置 TEMP/TMP；本机模拟 HTTP 需要允许回环连接。
.local\runtime\python\python.exe -B -m unittest discover -s scripts -p 'test_*.py' -v
.local\runtime\python\python.exe -B scripts/selftest.py
.local\runtime\python\python.exe -B scripts/check_architecture.py
```

`.local/runtime/python/` 是本机已有运行时，不是仓库随附环境；新克隆按 [agent.md](agent.md) 创建 `.venv`。全量回归日志、最终专项日志、自检日志与预览留在忽略目录 `.local/english-preview/`，没有把本机产物提交到 Git。

### 环境问题与失败复核

第一次受限运行的本机 HTTP 请求被沙箱拒绝（WinError 10013），中止后改用允许回环连接的执行环境重跑；AI 服务相关测试与自检随后通过。初次系统临时目录还出现 WinError 5，改用隔离临时目录后英语数据库测试通过。

完整 257 项运行仍出现两个既有小伙伴用例异常：

- `test_final_revision_read_failure_preserves_old_pointer` 在准备旧素材包时 `os.replace` 报 WinError 5；改用新的系统隔离临时目录，整个 `test_companion_packs.py` 的 7 项均通过。
- `test_write_failure_keeps_draft_and_previous_saved_creation` 的首次 `save_draft()` 返回 None，随后出现 AttributeError；同一用例单独重跑通过。没有定位该次首次保存失败的底层原因，不把它描述为已证明的目录权限问题。

小伙伴实现与这两个既有测试未修改。独立重跑通过不能把原全量结果改写为全绿，也不能证明没有环境相关偶发问题。

### 未验证项

未构建本次冻结包和安装包，未执行真实跨版本安装、卸载、UAC 或安装后数据保留检查；安装交接测试使用假进程/假安装包。没有完成更新失败后的真实全局输入钩子恢复、真实中文 IME、多显示器与 Windows DPI 人工体验，也没有执行在线 GitHub 安装包下载。离屏预览不是这些场景的替代证据。

数据库迁移 2 已用隔离库验证版本 0 初始化、版本 1 增量升级、历史数据保留、升级前备份和失败原子回滚。没有升级用户真实数据库。发布前按 [更新说明](updates.md) 与 [维护指南](agent.md) 在干净 Windows 环境完成剩余人工验证。


## 2026-10-13 0.9.5 发布准备

用户已授权发布 0.9.5。功能提交 `2bf43a703d4411279162009fbdbad722dcfc99ad` 的 [GitHub 回归](https://github.com/JeropsWang/typing-tracker/actions/runs/38389977241) 已通过：259 项回归、103 项自检。这是干净 Windows CI 的结果，不改写前述本机 257 项运行中的两项异常。

本次把源码版本更新为 0.9.5，补充从正式 0.9.4 安装包升级的 CI 检查，以及读取实际冻结包内更新代码的安装类型验证。正式附件继续为安装 EXE、便携 ZIP、manifest 与 SHA256SUMS；可通过草稿加 `publish_draft=true` 在全部构建与安装检查成功后公开。

修复旧 CI 自检中以自然日设置挑战经验上限的夹具：改用挑战时钟与 AppCalendar 应用日。旧 [9475c4e CI](https://github.com/JeropsWang/typing-tracker/actions/runs/38342543898) 的 230 项回归成功，自检在 UTC 凌晨 3 点失败于每日经验上限；产品计分代码未改变。本机常规自检与仅注入凌晨 3 点挑战时钟的自检各 103 项通过，更新专项 17 项、架构检查通过。

新工具 `scripts/verify_release_updates.py` 可使用源码或已验证冻结包内的更新模块，匿名读取正式 latest、模拟旧版本号、实际下载校验安装包，再以真实 GitHub SHA256SUMS 和相同的已下载字节验证回退；不会运行安装器。正式发布后的在线结果与链接将记录在 Release 和本次交付中。0.9.4 旧正式包没有自动更新功能，首次进入 0.9.5 需手动安装。

## 2026-10-13 0.9.5 正式发布与在线更新验证

[PR #7](https://github.com/JeropsWang/typing-tracker/pull/7) 已合并，标签 `v0.9.5` 对应源码 `2ac856b3dd9484a8390681a088c9a99eab1b6b6b`。[正式 Release](https://github.com/JeropsWang/typing-tracker/releases/tag/v0.9.5) 已公开，latest API 返回该版本，四个附件齐全，非草稿、非预发布。后续验证文档提交不改变此标签和附件。

| 检查 | 实际结果 |
| --- | --- |
| [master 回归与自检](https://github.com/JeropsWang/typing-tracker/actions/runs/38393122536) | 259 项回归、103 项自检全部通过 |
| [正式构建与发布](https://github.com/JeropsWang/typing-tracker/actions/runs/38393242342) | 干净 Windows 安装、卸载、0.9.2/0.9.3/0.9.4 升级及数据保留检查通过；实际安装路径的冻结更新模块识别为安装版 |
| 源码在线更新 | 匿名访问 GitHub；模拟当前版本 0.9.4 时发现 0.9.5，真实下载安装包并验证大小、GitHub digest 与 SHA256SUMS 回退；当前版本 0.9.5 无重复更新 |
| 正式便携包在线更新 | 先验证 ZIP 的 GitHub digest，读取其中实际发布 EXE 的冻结更新模块；同样通过旧版本检测、真实安装包下载及两种校验；正确识别为便携版 |
| 本机数据与安装操作 | 使用隔离缓存；两次在线验证均未启动安装器，未修改真实用户数据库 |

安装包为 `Sariana-0.9.5-windows-x64-setup.exe`，大小 107590289 字节，SHA-256 为 `038c0d8d4e63b6a69602b44e5a8dfc50c4e34b235945bc4c483d3d3636ae723a`。便携 ZIP 大小 105859269 字节，SHA-256 为 `35a95746420f6ceafe1ab8c12f56afce2a9445068958ee46e57c6e9dfbef27a4`。构建 manifest 的源码提交与标签一致。

本机报告留在忽略目录 `.local/release-0.9.5/live-source-report.json` 和 `.local/release-0.9.5/live-frozen-report.json`；可按 [更新说明](updates.md) 使用 `scripts/verify_release_updates.py` 复现。SHA256SUMS 回退读取真实 GitHub 校验附件，复用同一次下载的安装包字节。

这些结果补充了先前未完成的在线下载、冻结包和干净 Windows 安装升级验证。完整 GUI 的确认退出、安装向导交接及重新启动仍未人工操作验证；真实 IME、多显示器与 Windows DPI 体验仍待人工检查。旧 0.9.4 正式包没有更新功能，首次升级 0.9.5 必须手动安装；模拟旧版本号验证的是 0.9.5 更新实现。
