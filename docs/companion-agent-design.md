# 桌宠智能体视觉参考与转译

研究日期：2026-10-14。功能与三期边界见 [companion-agent.md](companion-agent.md)。本页记录公开网页的观察和 Widgets 设计映射，不将参考站的角色、商标、图片或脚本带入项目。

## 公开参考与已观察范围

通过联网检索确认两个官方入口，再用 REA 6.4.0 的 `capture_browser_scenario` 启动独立 Chrome 无头实例。网页截图视口为 1440×1000；使用空配置、无账户登录，不触及用户浏览器数据。

- [Blue Archive 日服官网](https://bluearchive.jp/)：捕获首页 DOM、可访问文本和截图；点击顶部 NEWS，等待后捕获实际新闻页。另读取页面声明的两份公开 CSS。
- [NEKOPARA 官网英文入口](https://nekopara.com/en/)：捕获首页 DOM、可访问文本和截图；读取页面声明的 common/main CSS。轮播圆点点击与翻页观察在用户中断时停止，未计入已验证交互。

## 可复用设计映射

以下前两列描述观察事实，最后一列是 Sariana 的设计选择。轮盘几何、不对称对话轮廓和桌宠状态联动均由本项目重新实现，不声称参考站已有相同组件。

| 参考组件 | 观察事实与证据 | 转译到 PySide6 Widgets |
| --- | --- | --- |
| Blue Archive 透明导航与错落入口 | 首页顶栏是深蓝半透明层、白字与青色选中标识；右下多个入口尺寸不同、共同落在底沿。截图 B1、样式 B3。 | 以桌宠为中心布置弧形轮盘；搜索为较大的主按钮，另两项较小。用淡紫玻璃底、薄荷描边和局部暖粉高亮形成颜色差分，保留透明区域与外圈刻度。 |
| NEKOPARA 图标叠层反馈 | 导航图标通过伪元素叠层改变透明度，样式给出约 0.3 秒的过渡；首页轮播圆点区以白色托盘跨越大图边缘。截图 N1、样式 N3。 | 使用 QPainter 绘制透明线性图标，hover 时浮起少量像素并出现环形光晕。小卡片的徽签跨越上沿，主轮廓采用不同圆角和轻微偏置尾巴，文字区保持水平。 |
| Blue Archive 新闻信息层级 | NEWS 点击后实际到达 `/news/newsJump`；页面把人物与深色内容板重叠，青色分类胶囊、细分隔线、右对齐时间形成阅读层级。运行 B2、样式 B4。 | 配置窗口分成角色侧栏和主要表单，使用不同底色区分模型、搜索与连接状态。结果卡片将状态徽签、正文和来源分层；详情保留独立滚动区，避免所有控件处于同一种平面。 |
| NEKOPARA 圆点与节奏 | 轮播 DOM 有四个圆点，CSS 给出桌面 12 像素圆形、灰色未选中与橙色选中；加载样式声明了错峰循环。DOM N1、样式 N3；没有实测轮播切换或加载动画帧。 | 将小圆点作为步骤/来源状态的视觉语言；思考时使用轻量错峰亮点和短句，完成后停止循环。取消或关闭时停止动画，避免后台仍在刷帧。 |
| Blue Archive 状态色与显隐 | 公开 CSS 为移动导航声明平移显隐和约 0.5 秒过渡，首页背景透明度声明约 0.3 秒过渡。静态样式 B3；未运行移动端菜单。 | 在 Qt 主线程以 QVariantAnimation/QTimer 控制轮盘展开、卡片出现与思考光晕；视觉状态统一跟随已有搜索进度。开始时桌宠进入专注反馈，成功时轻量回应，取消/失败时回到原状态。 |

## 本项目的组合规则

层次来自颜色、重叠和大小，不靠密集装饰：奶白/淡紫作为内容底，薄荷承担搜索与连接成功状态，暖粉承担角色与交互高亮；正文使用深色保证可读性。倾斜和不均衡只放在徽签、轨道和外轮廓，输入文字、表单与报告正文保持稳定对齐。

输入框、小卡片、状态徽签、按钮图标共享绘制语言。搜索卡片仍支持用户滚动；流式更新不能把已向上阅读的内容强行拉到底。轮盘项保持可点击区域、标签与 tooltip，透明绘制不等于缩小命中范围。尚未实现的汇报、占卜入口沿用 [三期计划](companion-agent.md)，不能用视觉状态暗示后台已经具备能力。

联动使用已有 Presenter 的进度与请求状态，通过 Qt 主线程更新 QWidget；后台不访问控件。配置仍由已有异步保存流程提交，UI 改造不增加数据库、网络或跨模块旁路。实现入口为 [agent_widgets.py](../app/ui/companion/agent_widgets.py)、[agent_settings.py](../app/ui/companion/agent_settings.py)、[agent_controller.py](../app/ui/companion/agent_controller.py) 和 [agent_visuals.py](../app/ui/companion/agent_visuals.py)。

## REA 证据索引

### 明日方舟参考追加（2026-10-14）

用户希望配置页更花哨、增加不规则图形并参考明日方舟官网。用 REA 独立 Chrome 无头实例、空配置在 1440×900 视口分别打开 [官网首页](https://ak.hypergryph.com/#index) 和 [情报页](https://ak.hypergryph.com/#information)，等待 5 秒后捕获 DOM、截图及最终 URL。普通网页读取工具曾超时，但浏览器捕获成功。没有登录账户。

| 已观察视觉 | 本项目转译 |
| --- | --- |
| 首页把角色大图、半透明青色色块和超大 ARKNIGHTS 文字叠在不同层，部分字形跨出画面 | 使用当前桌宠的本机素材作头图，加入大色块、局部裁切的 S 和分区编号；继续使用紫/蓝/珊瑚色 |
| 右侧边界有独立编号与首页标记，顶栏以英文大字加中文小标签区分章节 | 配置导航改为错位的独立按钮；不同章节同步窗口底色、控件色与操作高亮 |
| 情报页左侧列表和右侧主图宽度不同，细线分割，背景有大字和网点纹理 | 主表单配较窄的侧边便签，未来功能卡错位摆放；用线条、点阵、斜线和大编号增加层次 |
| 两个页面共用相同导航，当前分区从 INDEX 高亮切换为 INFORMATION 高亮 | 分区选择由单一状态驱动颜色与选中按钮；移除会露出平台深色底板的原生文档页签 |

切角、折页、撕边与星形几何是本项目的原创补充，不声称官网存在完全相同的组件。图形由 `agent_settings_art.py` 原生 QPainter 绘制，不引入网页运行时；文字与输入区保持水平。只使用本项目已有桌宠作品，不将官网人物、图片或脚本带入产品。

| 捕获 | Evidence ID |
| --- | --- |
| 首页 DOM、截图、最终 `#index` URL | `ev_8600d842f7c7e12d27b5153ef309e9c75eba92eac3ce2d61607c10c80552e6e0` |
| 情报页 DOM、截图、最终 `#information` URL | `ev_f43d308829142fc31a1b5422d78d8b434626b92abe63bd006d85fda333b9868a` |

这是直接导航后的两个静态状态观察；未测点击跳转、hover、逐帧动画或移动布局。REA 的 `complete` 指本次要求的三个捕获项齐全，不代表整站交互已验证。

### 先前公开参考

Evidence ID 是本次 REA 会话的定位符，不是可公开下载的附件。以下记录来自成功完成的捕获；`complete` 仅代表本次请求的捕获项齐全，不代表整站或所有动效已验证。

| 编号 | 目标与捕获 | Evidence ID |
| --- | --- | --- |
| B1 | [Blue Archive 首页](https://bluearchive.jp/)，等待 5 秒后的截图、DOM、可访问文本 | `ev_9431940308926b66a57ef801025c0ac73c68cb6b6b62ade09e17ec3a39f23e65` |
| B2 | 点击 NEWS 后的[新闻页](https://bluearchive.jp/news/newsJump)，截图、DOM、可访问文本与 URL | `ev_068bc87822dac759354e2e220012482dcbc819a48b57e6b09780442ec60d0cf6` |
| B3 | [Blue Archive 主样式](https://webusstatic.yo-star.com/bluearchive_jp_web/css/app.47b744a6.css)，直接请求的 CSS 响应 | `ev_c06b1bbdaf3ffa2f639f439bfb9e41b8c64662eca9624a8f43fc5473c3a1a20a` |
| B4 | [Blue Archive 新闻样式](https://webusstatic.yo-star.com/bluearchive_jp_web/css/view-newsJump-vue.4287000e.css)，直接请求的 CSS 响应 | `ev_6840411bffcdb81e29f18c87cbaeccc5f6c7b096e865a57356bb5d89b8aaa469` |
| N1 | [NEKOPARA 英文首页](https://nekopara.com/en/)，等待 5 秒后的截图、DOM、可访问文本 | `ev_ab1f07d6ddc992a459f5c3323096cb70175645f971fd45becba7ce90ed1f7ecc` |
| N2 | [NEKOPARA 基础样式](https://nekopara.com/css/common.css?v=1.1.0)，直接请求的 CSS 响应 | `ev_36fe395324c7a9ca77c95e8a035527a8b18dd2c1f38fbc684e4d10afe94c8c41` |
| N3 | [NEKOPARA 主样式](https://nekopara.com/css/main.css?v=1.1.0)，直接请求的 CSS 响应 | `ev_232fc05de4da01d0c21ed5f15d2a11332c0c8b52d0f1971e8580050428489c02` |

## 局限与验证

本次运行观察覆盖两站桌面首页和 Blue Archive 的 NEWS 导航；未做手机断点、hover 的逐帧测量、轮播按钮切换、浏览器跨平台比较。CSS 的过渡和动画声明是静态证据，不能当作已经观察到执行。公开页面或带构建散列的 CSS URL 后续可能改变。

网页截图和角色素材仅用于研究观察，不保存到生产资源；项目采用自己的几何形状、图标与现有桌宠素材。此文档变更只检查本地引用路径和格式；实现回归、Qt 预览以及 DPI/多显示器/输入法人工检查由实际 UI 改动另行记录，不能从网页研究推导为通过。
