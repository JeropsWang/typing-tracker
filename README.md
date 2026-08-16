# 打字管家（TypingTracker）

本地单机桌面打字统计应用（Python + PySide6 + pyqtgraph）。当前进度：**M4 主题插件系统完成，打包验证中**。

## 功能

- 后台全局键盘采集（Windows ctypes 低层钩子），关窗驻留系统托盘
- **IME 增强计数**：中文输入法组字不按按键计，按**上屏字符**计（汉字 = 2tw、字母 = 1tw），组字中退格不计删除。
  - v0.3 修复：重写上屏检测（`ImeCommitTracker`）——结果串优先 + 组字串前缀丢失兜底，**连续打字（选字后立即打下一组拼音）不再丢失**；中文标点直接提交也计入；组字内退格/Esc 取消不误计；鼠标选字由 1 秒轮询兜底
  - v0.3.1 修复（关键）：`_foreground_process` 曾误挂 `user32.OpenProcess`（该 API 在 kernel32），导致**每次按键都在排除程序检查处抛异常、全部漏计**——已改挂 kernel32，并新增"钩子回调异常可见"（`hook.errors`）与 DLL 归属静态检查防回归
  - v0.3.2 修复：钩子线程的 SQLite 跨线程调用（日切起点查询 / 排除列表查询）——改为**构造时缓存 + 设置变更时快照刷新**，钩子线程零 SQLite
  - v0.4 **TSF 精确中文计数**：comtypes 手写 TSF COM 绑定（`tsf_bind.py`，按 SDK msctf.idl 顺序）+ 组字监听（`tsf_hook.py`：焦点上下文轮询组字串，提交时读取 TSF range 的**最终文本** = 精确上屏汉字）；TSF 感知窗口（Edge/Office/VS Code 等）中文按**上屏汉字**精确计；传统窗口自动回退 IMM/按键近似
  - 诊断：`python scripts/hook_probe.py --seconds 20`（RAW 原始事件 + 异常堆栈 + TSF 状态）、`python scripts/hook_e2e_test.py`（注入 A+退格自动验证全链路）
- 组合键过滤（Ctrl/Alt/Win）与**排除程序列表**；主界面显示钩子运行状态（失败会明确提示）
- 按日统计：输入/删除/有效字数、tw、平均速度、正确率（日指标，不并入终身总计）；终身总计仅总量类指标
- **统一度量衡 tw + 三预测**：平均 tw/分、预测汉字数/分（÷2）、预测字母数/分（×1），单位名可自定义
- **可视化报表**：趋势分析（7/30/90 天，tw/汉字/字母三视角）、年度打卡热力图、24 小时时段分布、周月报对比
- **打卡 + 等级**：每日自动打卡、连签奖励、连签里程碑礼包（3/7/14/30/60/100/200/300 天）、补签卡恢复连签、`cost(n)=40+2n`（纯连签约 300 天满级 100，可开无限等级之路）
- **37 项成就**：速度/字数/每分钟正确率/总正确率，解锁后**手动领取**（经验/补签卡/经验加成卡/称号）
- **鼓励机制**：近 7 日速度较前 7 日上升 ≥15% 触发（72h 冷却），奖励补签卡/加成卡/经验包
- **打字经验**：每 1000 有效字 +5（每日上限 300），经验加成卡 ×2（30 分钟）
- **主题插件系统**：内置浅色/深色/**梨诺 v2（偶像舞台·星空紫：深紫星空 + 金色闪烁星星 + 舞台聚光灯渐变 + 粉色偶像感 accent）**，支持 .zip 导入、实时预览、删除（见 `THEMES.md`）
- **动态美感（二次元可爱风）**：
  - 星空粒子背景（`StarField`：程序化绘制 + 正弦闪烁 + 十字光芒，随主题配色动态变化）
  - 酷炫等级条（`LevelBar`：渐变填充 + 扫光动画 + 分段刻度 + 星星点缀）
  - 成就/升级/鼓励**小弹窗**（`ToastPopup`：圆角卡片 + 淡入动画 + 星星装饰 + 自动消失，右上角堆叠）
  - Tab 切换页面淡入、等级徽章发光、卡片圆角分组、升级弹窗（Lv.N → Lv.N+1）
- **数据备份导出**：设置 → 导出数据备份（daily_stats.csv + data.json）
- 设置：单位名、日切起点（默认凌晨 4 点）、无限等级、排除程序

## 运行

```powershell
# 方式一：本地依赖目录（.deps）
python scripts/fetch_deps.py   # 或：python -m pip install --target .deps PySide6
python main.py

# 方式二：正常 venv / 系统环境
python -m pip install -r requirements.txt
python main.py
```

数据目录默认 `%APPDATA%/TypingTracker/`（可用 `--data-dir` 指定）。

## 自检

```powershell
python scripts/selftest.py              # 无 GUI 逻辑自检（56 项，含 IME 连续打字回归）
python scripts/hook_probe.py --seconds 15   # 键盘钩子诊断：15 秒内打印捕获到的事件
python scripts/smoke_ui.py              # 离屏 GUI 冒烟
python scripts/seed_demo.py --data-dir .demo   # 生成 119 天演示数据，预览报表
python scripts/screenshot.py --data-dir .demo --tab 1   # 离屏渲染报表页为 PNG
```

## 里程碑

- [x] M1 骨架：钩子（IME 增强）+ 存储 + 托盘 + 今日概览 + 基础设置
- [x] M2 报表：tw 三预测 + 趋势图/热力图/时段分布/周月报（pyqtgraph）
- [x] M3 游戏化：37 成就（手动领取）+ 鼓励机制 + 补签卡/经验加成卡 + 打字经验 + 连签里程碑礼包 + 成就页/打卡页 UI
- [x] M4 主题插件系统（导入/预览/删除 + 图表配色联动 + 内置浅/深色）+ 备份导出 + PyInstaller 打包（`dist/TypingTracker.exe`，已验证运行）
- [x] M5 「明日方舟：终末地 · 梨诺」内置主题 + 分发 zip（`releases/`）

全部完成 🎉

详见 `../打字追踪应用设计方案.md`。
