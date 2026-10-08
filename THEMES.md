# 主题插件开发指南（TypingTracker）

主题 = 一个文件夹（或 .zip 压缩包），包含以下文件：

```
my-theme/
├── manifest.json     # 必填：元数据 + 配色变量
├── theme.qss         # 必填：Qt 样式表（支持占位符）
├── charts.json       # 可选：图表配色（趋势/热力图/时段分布）
└── assets/           # 可选：图片素材（logo 等，后续版本支持）
```

## manifest.json 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | ✅ | 唯一标识（英文/数字/下划线），不能与内置主题冲突 |
| `name` | ✅ | 展示名称（如「萨莉安娜」） |
| `version` | 否 | 版本号 |
| `author` | 否 | 作者 |
| `base` | 否 | 浅色/深色基调：`light` / `dark` |
| `colors` | ✅ | 配色变量，供 theme.qss 占位符引用 |
| `fonts` | 否 | `{"family": "字体名"}` |

## 占位符

`theme.qss` 中可用 `{{colors.变量名}}`、`{{fonts.family}}` 引用 manifest 中的值，
ThemeManager 在应用时自动替换。未知变量替换为空字符串。

## charts.json 字段

| 字段 | 说明 |
|------|------|
| `background` | 图表背景色 |
| `grid` | 网格线与坐标轴颜色 |
| `speed` | 速度曲线颜色 |
| `acc` | 正确率曲线颜色 |
| `chars` | 字数曲线颜色 |
| `levels[5]` | 打卡热力图 5 档颜色（浅→深） |
| `empty` | 热力图无记录格颜色 |

## 导入

设置 → 主题插件 → 导入主题…（选择 .zip）→ 即时预览生效。
用户主题存放在数据目录 `themes/` 下，可删除；唯一内置主题「萨莉安娜」不可删除。

## 内置示例

`app/theme/themes/arknights_endfield_lino/` 是唯一的规范示例，可复制修改（第三方主题照旧可导入、可删除）。
目录标识保留以兼容旧设置，界面展示名称使用「萨莉安娜」。
打包分发时只需把主题文件夹打成 zip（根目录含 manifest.json 即可，多层目录也支持）。
