"""全局调色板（单例）：主题切换时更新，所有页面的文字/卡片颜色从这里取。

修复：v0.5 曾硬编码浅色系文字颜色（#6b7280 等），深色星空主题下
对比度不足——现在统一由主题 colors/effects 派生，保证任何主题下可读。
"""
from __future__ import annotations


class _Palette:
    def __init__(self):
        self.reset()

    def reset(self):
        """浅色主题默认值。"""
        self.dark = False
        self.text = '#111827'
        self.muted = '#6b7280'
        self.faint = '#9ca3af'
        self.accent = '#3b82f6'
        self.success = '#10b981'
        self.warn = '#f59e0b'
        self.card_bg = 'qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,242), stop:1 rgba(255,255,255,196))'
        self.card_border = 'rgba(255, 255, 255, 235)'
        self.shadow_color = '#6366F12E'   # #AARRGGBB，QGraphicsDropShadowEffect 用
        self.badge_bg = 'rgba(255, 255, 255, 0.62)'
        self.badge_border = '#fbbf24'
        self.badge_text = '#b45309'
        self.mini_bg = '#FFFFFF66'      # 迷你图表背景（#AARRGGBB，pyqtgraph 用）
        self.cal_missed = '#f3f4f6'      # 打卡日历：已过未打卡
        self.cal_future = '#e5e7eb'      # 打卡日历：未来

    def update(self, colors: dict, effects: dict):
        self.dark = bool(effects.get('dark', False))
        colors = colors or {}
        self.text = colors.get('text', '#111827')
        self.muted = colors.get('muted', '#6b7280')
        self.faint = colors.get('muted', '#9ca3af')
        self.accent = effects.get('accent', colors.get('primary', '#3b82f6'))
        self.success = colors.get('success', '#10b981')
        self.warn = colors.get('warn', '#f59e0b')
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


P = _Palette()
