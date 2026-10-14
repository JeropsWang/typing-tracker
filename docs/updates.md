# GitHub 正式版本更新

应用从 `JeropsWang/typing-tracker` 的公开 GitHub Releases 检查正式版本，不需要 Token。默认开启启动后延迟检查，同一数据目录的自动检查间隔至少 24 小时；失败也记录检查时间，避免网络故障时每次启动都请求。设置的「数据备份」分组包含自动检查开关、当前版本、检查按钮和更新状态。自动检查失败只更新状态，不弹窗。

GitHub 匿名 REST 请求按网络出口 IP 共用每小时 60 次额度，不是每个桌宠独享；代理或同一网络中的其他工具也可能消耗额度。收到明确限流时，源码更新器依据 `Retry-After` / `X-RateLimit-Reset` 显示预计恢复的本机时间，并在该时间之前阻止重复检查；自动检查仍保持原有每天一次的规则，不新增轮询。没有限流证据的普通 403 单独提示拒绝访问，错误正文和出口 IP 不进入用户提示。依据见 [GitHub 官方限流说明](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)。

「打开版本页 · 手动下载」始终可用，使用固定仓库的官方最新版本网页，不依赖 REST 查询；此入口不自动下载、安装或退出应用。限流冷却仅针对 API 检查，已经确认来源和摘要的安装附件仍可独立下载、核验。2026-10-14 重新发布的 0.9.6 附件已包含这项修复，0.9.5 和最初发布的旧 0.9.6 附件没有此入口；同版本不触发升级提示，安装旧 0.9.6 的用户须手动重新下载安装。

更新控制器的防重入从 0.9.5 起已经存在：Qt 主线程先设置 `busy` 并禁用检查按钮，再启动一个后台任务，只有完成回传或错误回传才恢复；手动/自动入口共用同一状态，没有直到成功的循环重试。传输层设置 20 秒网络超时，但这不是整个任务的绝对截止时间。若增加总体超时提醒，应保留在途资格直到后台确实结束，不能仅因定时器到点就清除忙碌状态或再发一份请求；线程死锁属于需要避免的故障，不是恢复机制。

安装版支持「检查 → 用户下载 → 校验 → 确认退出 → 安装向导」。便携版提供对应正式 Release 的 Windows x64 ZIP 下载入口，源码运行只展示版本信息。冻结程序的目录必须与稳定 AppId `{8A3CAB17-B864-4379-9BAA-A2C7AE85706D}` 的 Inno Setup 安装记录一致才识别为安装版；同机其他目录的便携副本不会误判。

## 下载与发布兼容

- 发布继续使用现有 [Windows 工作流](../.github/workflows/windows-release.yml) 和 [构建脚本](../scripts/build_release.py)，无需新增服务或修改安装 AppId。
- 接受 `Sariana-版本-windows-x64-setup.exe` 和旧品牌 `TypingTracker` 的同规格附件；便携包后缀为 `windows-x64-portable.zip`。草稿、预发布和不高于当前版本的正式版本被忽略。
- 安装包存入数据目录的 `update-cache/`，不覆盖正在运行的程序。下载可取消，失败和取消会清理 `.partial` 文件。
- 完整下载必须匹配附件大小和 SHA-256。优先使用附件 `digest`，缺失时读取同 Release 的 `品牌-版本-SHA256SUMS.txt`。缺失、歧义或不一致时禁止安装，启动安装前再次校验。
- 入口必须属于固定仓库；网络只接受 GitHub HTTPS 与其 Release 附件 CDN 重定向。网络请求不进入数据库事务，网络线程不接触 QWidget。

GitHub 协议依据：[Releases REST API](https://docs.github.com/en/rest/releases/releases#get-the-latest-release)。

0.9.4 及更早正式包没有更新功能，第一次进入 0.9.5 需要手动安装。在线验证使用新版本的更新代码并传入旧版本号，不把它描述成旧包已具备更新能力。

发布 0.9.5 起可先创建草稿 Release，再手动运行 Windows 工作流，设置 `tag=v0.9.5`、`publish_draft=true`。构建、安装/卸载、0.9.2/0.9.3/0.9.4 升级检查全部成功并上传四个附件后，工作流才公开草稿并标为 latest。历史附件回填默认不公开草稿。工作流使用 GITHUB_TOKEN 发布，避免再次触发重复的发布构建；见 [GitHub 工作流触发规则](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)。

## 可重试退出

Qt 协调器检查练习、未保存结果和正在提交的命令。提交中拒绝安装；未完成学习必须完成或明确选择放弃。确认后停止采集和周期任务，串行工作线程排空已受理命令，再提交最终统计。

`DesktopApplication.prepare_update_exit()` 返回 Future，在提交成功前不关闭数据库线程；失败保留脏统计并恢复命令接收，界面恢复采集与定时保存，用户可重试。`finish_update_exit()` 只允许最终保存成功后执行，并异步关闭数据库线程。

成功保存后启动隐藏辅助进程，数据库关闭成功后才写入本次更新的随机授权标记，然后释放单实例锁并退出。辅助进程等待主进程实际退出，要求授权标记匹配，再次校验缓存安装包，然后打开可见的原 Inno Setup 向导。关闭失败会取消本次辅助进程；标记缺失、等待超时或校验失败时不安装。向导沿用安装 AppId、原安装目录和数据目录，是否启动新版由用户在向导中选择。

## 验证

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = '.deps' # 使用本仓库本地依赖时
python -B -m unittest discover -s scripts -p 'test_updates.py' -v
python -B scripts/check_architecture.py
```

发布后的真实检查可用：

```powershell
python -B scripts/verify_release_updates.py --expected-version 0.9.5 --older-version 0.9.4 --cache-dir .local/release-update-check --output .local/release-update-check/result.json
```

该工具匿名访问 GitHub latest，实际下载并校验安装包，以真实 GitHub SHA256SUMS 加已下载的相同安装包字节验证回退，再确认当前版本不重复提示。不会启动安装器。可加 `--exe` 指向本仓库已验证的冻结程序，执行包内更新代码；安装烟测用 `--detect-installation-only --require-installed` 核对真实安装记录与冻结程序目录。

测试使用内存 GitHub 响应和临时数据库，覆盖版本、受信任地址、缺少附件、SHA256SUMS 回退、限流、断网、取消、包损坏、安装类型、检查频率和真实数据库线程最终保存失败后重试。真实安装升级、UAC、安装向导显示、全局输入钩子恢复和安装后数据保留，需在干净 Windows 测试机按 [维护指南](agent.md) 验证；离屏测试不能替代这些验证。
