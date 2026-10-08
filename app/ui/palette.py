"""全局调色板（单例）：主题切换时更新，所有页面的文字/卡片颜色从这里取。

修复：v0.5 曾硬编码浅色系文字颜色（#6b7280 等），深色星空主题下
对比度不足——现在统一由主题 colors/effects 派生，保证任何主题下可读。
"""
from __future__ import annotations


def mix(color_a: str, color_b: str, weight_a: float) -> str:
    """按权重混合两个 #RRGGBB 颜色（weight_a 为 color_a 的占比）。"""
    def parts(value: str):
        value = value.lstrip('#')
        return [int(value[i:i + 2], 16) for i in (0, 2, 4)]

    try:
        a, b = parts(color_a), parts(color_b)
    except (ValueError, IndexError):
        return color_a
    out = [round(a[i] * weight_a + b[i] * (1 - weight_a)) for i in range(3)]
    return '#%02X%02X%02X' % tuple(max(0, min(255, c)) for c in out)


class _Palette:
    def __init__(self):
        self.reset()

    def reset(self):
        """浅色主题默认值。"""
        self.dark = False
        self.background = '#f5f6fa'
        self.surface = '#ffffff'
        self.primary = '#1d4ed8'
        self.primary_text = '#ffffff'
        self.text = '#111827'
        self.muted = '#6b7280'
        self.faint = '#9ca3af'
        self.accent = '#3b82f6'
        self.success = '#047857'    # 深绿：浅色背景对比度达标（审计修复）
        self.warn = '#b45309'       # 深琥珀：浅色背景连签/里程碑可读（审计修复）
        self.danger = '#dc2626'     # 深红
        self.card_bg = self.surface
        self.card_border = '#d1d5db'
        self.border = self.card_border
        self.shadow_color = '#6366F12E'   # #AARRGGBB，QGraphicsDropShadowEffect 用
        self.badge_bg = 'rgba(255, 255, 255, 0.62)'
        self.badge_border = '#fbbf24'
        self.badge_text = '#b45309'
        self.mini_bg = '#FFFFFF66'      # 迷你图表背景（#AARRGGBB，pyqtgraph 用）
        self.cal_missed = '#f3f4f6'      # 打卡日历：已过未打卡
        self.cal_future = '#e5e7eb'      # 打卡日历：未来
        # ---- 交接 spec.json 的语义角色（深色画布 + 奶油纸张）----
        self.canvas = '#f5f6fa'          # 画布/窗口底色
        self.paper = '#ffffff'           # 纸张表面（不透明）
        self.paper_text = '#111827'      # 纸张上的正文
        self.paper_muted = '#6b7280'     # 纸张上的辅助文字
        self.surface_text = '#111827'    # 深/浅表面上的文字
        self.surface_muted = '#6b7280'
        self.accent_rose = '#d79d96'     # 玫瑰点缀（少量）
        self.accent_ochre = '#c4b78c'    # 赭金点缀（少量）
        self.focus = '#1d4ed8'           # 键盘焦点轮廓
        self.focus_on_paper = '#1d4ed8'  # 纸张上的焦点轮廓（浅紫在奶油纸上不可见）
        self.success_on_paper = '#346453'
        self.danger_on_paper = '#963f52'

    def update(self, colors: dict, effects: dict):
        self.dark = bool(effects.get('dark', False))
        colors = colors or {}
        self.background = colors.get('background', '#f5f6fa')
        self.surface = colors.get('card', '#ffffff')
        self.primary = colors.get('primary', '#1d4ed8')
        # 亮色按钮用深文字、暗色按钮用白文字；用户主题也能安全回退。
        from PySide6.QtGui import QColor
        color = QColor(self.primary)
        channels = [c / 255 for c in (color.red(), color.green(), color.blue())]
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        lum = sum(c * w for c, w in zip(linear, (.2126, .7152, .0722)))
        self.primary_text = colors.get('on_primary', '#171525' if lum > .20 else '#ffffff')
        self.text = colors.get('text', '#111827')
        self.muted = colors.get('muted', '#6b7280')
        # faint 单独读 faint 键；主题只定义 muted 时沿用 muted（曾误读 muted 导致
        # 主题定义的 faint 永远失效，且浅色兜底 #9ca3af 对比度仅 2.54:1）
        self.faint = colors.get('faint', colors.get('muted', '#6b7280'))
        self.accent = effects.get('accent', colors.get('primary', '#3b82f6'))
        # 交接规格的语义颜色：主题未定义时按明暗给出安全兜底，
        # 保证未迁移的浅色/默认深色主题仍可读（不改已有主题行为）。
        self.canvas = colors.get('canvas', self.background)
        self.surface_text = colors.get('surface_text', self.text)
        self.surface_muted = colors.get('surface_muted', self.muted)
        self.paper = colors.get('paper', '#EEE5D6' if self.dark else '#ffffff')
        self.paper_text = colors.get('paper_text', '#34313E' if self.dark else self.text)
        self.paper_muted = colors.get('paper_muted', '#625C68' if self.dark else self.muted)
        self.accent_rose = colors.get('accent_rose', colors.get('accent', '#d79d96'))
        self.accent_ochre = colors.get('accent_ochre', '#c4b78c')
        self.focus = colors.get('focus', self.primary)
        # 纸张上的焦点轮廓：spec 的浅紫焦点在奶油纸上对比度仅 1.4:1，
        # 按纸张正文方向混深到可辨识（≥4.5:1），主题可显式覆盖。
        self.focus_on_paper = colors.get(
            'focus_on_paper', mix(self.focus, self.paper_text, 0.32))
        self.success_on_paper = colors.get('success_on_paper', '#346453')
        self.danger_on_paper = colors.get('danger_on_paper', '#963f52')
        if self.dark:
            # 深色背景：亮色即可读
            self.success = colors.get('success', '#34d399')
            self.warn = colors.get('warn', '#f59e0b')
            self.danger = colors.get('danger', '#f87171')
        else:
            # 浅色背景：必须用深色调才能达到 WCAG 对比度（审计修复）
            self.success = colors.get('success', '#047857')
            self.warn = colors.get('warn', '#b45309')
            self.danger = colors.get('danger', '#dc2626')
        if self.dark:
            self.card_bg = 'qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(43,32,92,230), stop:1 rgba(30,23,66,215))'
            self.card_border = 'rgba(179, 157, 219, 70)'
            self.shadow_color = '#0000006E'
            self.badge_bg = 'rgba(41, 33, 96, 220)'
            self.badge_border = self.accent
            self.badge_text = self.text
            self.mini_bg = '#0000005A'
            self.cal_missed = 'rgba(255, 255, 255, 0.07)'
            self.cal_future = 'rgba(255, 255, 255, 0.04)'
        else:
            self.card_bg = 'qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,242), stop:1 rgba(255,255,255,196))'
            self.card_border = 'rgba(255, 255, 255, 235)'
            self.shadow_color = '#6366F12E'
            self.badge_bg = 'rgba(255, 255, 255, 0.62)'
            self.badge_border = '#fbbf24'
            self.badge_text = '#b45309'
            self.mini_bg = '#FFFFFF66'
            self.cal_missed = '#f3f4f6'
            self.cal_future = '#e5e7eb'
        # 面板和边框尊重主题角色，避免每页自己拼渐变色。
        self.card_bg = self.surface
        self.card_border = colors.get('border', '#d1d5db')
        self.border = self.card_border


P = _Palette()
