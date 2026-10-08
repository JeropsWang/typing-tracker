"""停靠导航组件：图标、选中反馈和摘要布局，不处理页面业务。"""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QWidget
from ..palette import P
from .responsive import NavigationLayout, bounded
from .motion import MotionValue
from .visual_tokens import (
    ICON_SIZE, FONT_BODY, SCALE_MIN,
    NAV_PILL_RADIUS, NAV_UNDERLINE_H, asset_path, is_dark_surface, nav_active_fill,
    nav_underline_color,
)

def nav_icon(name: str, size: int = ICON_SIZE, opacity: float = 1.0,
             device_pixel_ratio: float = 1.0) -> QIcon:
    """交付的多色导航图标；未选中时降低不透明度，仍可与文字一起表达选中。

    高 DPI 下按设备像素比渲染，避免 SVG 被放大后发虚。
    """
    path = asset_path('nav', f'{name}.svg')
    dpr = max(1.0, float(device_pixel_ratio))
    pixmap = QPixmap(int(size * dpr), int(size * dpr))
    pixmap.fill(Qt.transparent)
    if path.exists():
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(opacity)
        QSvgRenderer(str(path)).render(painter)
        painter.end()
    pixmap.setDevicePixelRatio(dpr)
    return QIcon(pixmap)


class NavButton(QPushButton):
    """图标与文字同排；选中用底色、字重和下划线表达，保持键盘操作。"""

    def __init__(self, title, icon_name, parent=None, *, compact: bool = False):
        super().__init__(title, parent)
        self.icon_name = icon_name
        self.setProperty('navItem', True)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(title)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._compact = bool(compact)
        self._hover = False
        self._hover_motion = MotionValue(self, lambda _: self.update())
        self._selection_motion = MotionValue(self, lambda _: self.update(), 220)
        self.setMouseTracking(True)
        self.set_compact(compact)
        self.toggled.connect(self._sync_icon)
        self.toggled.connect(lambda checked: self._selection_motion.animate_to(float(checked)))

    def set_motion_enabled(self, enabled):
        self._hover_motion.set_enabled(enabled)
        self._selection_motion.set_enabled(enabled)

    def _icon_size(self) -> int:
        return bounded(29 + 13 * getattr(self, '_density', float(not self._compact)), 29, 42)

    def _icon_opacity(self, checked: bool) -> float:
        """未选中图标的不透明度。

        交付图标是**多色插画**，配方第 128 行两种状态都是原样绘制；这里沿用旧的
        “未选中降不透明度”手法，但它会同时降低浅色主题下图标与其底色的对比度
        （`#9CA3AF` @0.62 叠在 `#FFFFFF` 上只有约 2.0:1），所以浅色表面用 0.85、
        深色表面用 0.70。选中态仍为 1.0，且选中表达不依赖颜色（底 + 加粗 + 下划线）。
        """
        if checked:
            return 1.0
        return 0.85 if not is_dark_surface(P.surface) else 0.70

    def _sync_icon(self, checked: bool) -> None:
        size = self._icon_size()
        key = (size, self._icon_opacity(checked), self.devicePixelRatioF())
        if key == getattr(self, '_icon_key', None):
            self.update()
            return
        self._icon_key = key
        self.setIcon(nav_icon(self.icon_name, size, self._icon_opacity(checked),
                              self.devicePixelRatioF()))
        self.setIconSize(QSize(size, size))
        self.update()

    def set_scale(self, scale: float) -> None:
        self.set_density(max(0.0, min(1.0, (scale - SCALE_MIN) / (1 - SCALE_MIN))))

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self.set_density(float(not compact))

    def set_density(self, openness):
        self._density = max(0.0, min(1.0, openness))
        icon = self._icon_size()
        pad = bounded(10 + 4 * self._density, 10, 14)
        gap = bounded(8 + 2 * self._density, 8, 10)
        text_w = 34
        item_h = bounded(52 + 16 * self._density, 52, 68)
        self.setFixedHeight(item_h)
        # 宽度：图标 + 间距 + 文字（按 16px 正文估宽）+ 左右内边距
        self.setMinimumWidth(icon + gap + text_w + 2 * pad)
        self._pad = pad
        self._gap = gap
        self.setIconSize(QSize(icon, icon))
        self._sync_icon(self.isChecked())

    # ---------- 悬停 ----------
    def enterEvent(self, event):
        self._hover = True
        self._hover_motion.animate_to(1)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._hover_motion.animate_to(0)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        # 不调用 super()：底栏外观完全由这里决定（QSS 只负责焦点轮廓）
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        checked = self.isChecked()

        selection = self._selection_motion.value
        hover = self._hover_motion.value
        if checked or selection > 0 or hover > 0:
            if checked or selection > 0:
                fill = QColor(nav_active_fill())
                fill.setAlphaF(selection)
            else:
                fill = QColor(P.surface_text)
                fill.setAlphaF(0.10 * hover)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            pill_width = min(rect.width(), 106 + 22 * self._density)
            inset = (rect.width() - pill_width) / 2
            p.drawRoundedRect(rect.adjusted(inset, 1, -inset, -1), NAV_PILL_RADIUS, NAV_PILL_RADIUS)

        icon_size = self._icon_size()
        gap = getattr(self, '_gap', 10)
        font = self.font()
        font.setPixelSize(FONT_BODY)
        font.setWeight(font.Weight.DemiBold if checked else font.Weight.Normal)
        metrics = self.fontMetrics()
        text_w = metrics.horizontalAdvance(self.text())
        content_w = icon_size + gap + text_w
        x = rect.left() + max(0.0, (rect.width() - content_w) / 2.0)
        icon_y = rect.top() + (rect.height() - icon_size) / 2.0
        pixmap = self.icon().pixmap(QSize(icon_size, icon_size),
                                    QIcon.Normal, QIcon.On if checked else QIcon.Off)
        if not pixmap.isNull():
            p.drawPixmap(QRectF(x, icon_y, icon_size, icon_size), pixmap,
                         QRectF(pixmap.rect()))
        p.setPen(QColor(P.surface_text if checked else P.surface_muted))
        p.setFont(font)
        text_rect = QRectF(x + icon_size + gap, rect.top(), text_w + 2, rect.height())
        p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self.text())

        if checked or selection > 0:
            underline_w = (56 + 5 * self._density) * selection
            underline_h = NAV_UNDERLINE_H
            y = rect.bottom() - (4 + 4 * self._density)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(nav_underline_color()))
            p.drawRoundedRect(
                QRectF(rect.center().x() - underline_w / 2.0, y - underline_h,
                       underline_w, underline_h), underline_h / 2.0, underline_h / 2.0)
        p.end()


class NavigationSummary(QWidget):
    """逐步展开用户摘要；空间不足时省略文字，避免挤压导航入口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.name = '打字新星'
        self.detail = ''
        self.icon_name = 'growth'
        self._icon_key = None

    def set_summary(self, name, detail, icon_name):
        self.name, self.detail, self.icon_name = name, detail, icon_name
        self.setAccessibleName(f'{name}，{detail}')
        self.setToolTip(f'{name} · {detail}')
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipRect(self.rect())
        size = min(44, max(0, self.width() - 16), self.height() - 8)
        if size < 24:
            painter.end()
            return
        key = (self.icon_name, size, self.devicePixelRatioF())
        if key != self._icon_key:
            self._pixmap = nav_icon(self.icon_name, size, .9, self.devicePixelRatioF()).pixmap(size, size)
            self._icon_key = key
        painter.drawPixmap(8, (self.height() - size) // 2, self._pixmap)
        x, width = size + 18, self.width() - size - 26
        if width < 30:
            painter.end()
            return
        font = self.font()
        font.setPixelSize(16)
        font.setWeight(font.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(P.surface_text))
        painter.drawText(QRectF(x, self.height() / 2 - 23, width, 24),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(font).elidedText(self.name, Qt.ElideRight, width))
        font.setPixelSize(13)
        font.setWeight(font.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(P.surface_muted))
        painter.drawText(QRectF(x, self.height() / 2 + 3, width, 20),
                         Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(font).elidedText(self.detail, Qt.ElideRight, width))
        painter.end()


class BottomNav(QWidget):
    """浮起的五项导航与弹性用户摘要，页面选择由 set_current 同步。"""

    selected = Signal(str)

    def __init__(self, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self.setObjectName('bottomNav')
        self.setMaximumWidth(NavigationLayout.MAX_WIDTH)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.buttons: dict[str, NavButton] = {}
        self._compact = bool(compact)
        self._density = float(not compact)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(16, 6, 16, 6)
        self._row.setSpacing(8)
        self._summary = NavigationSummary(self)
        self._summary.setFixedWidth(240)
        self._row.addWidget(self._summary)
        self._row.addStretch(0)
        self.set_compact(compact)

    def add_item(self, title: str, icon_name: str, *, enabled: bool = True) -> NavButton:
        button = NavButton(title, icon_name, self, compact=self._compact)
        button.setEnabled(enabled)
        button.clicked.connect(lambda _=False, name=title: self.selected.emit(name))
        self._group.addButton(button)
        self.buttons[title] = button
        self._row.insertWidget(self._row.count() - 1, button, 1)
        return button

    def set_summary(self, name: str, detail: str, icon_name: str = 'growth') -> None:
        """用户摘要按余量展开，文字省略时完整信息保留在提示中。"""
        self._summary.set_summary(name or '', detail or '', icon_name)
        self._sync_summary_visibility()

    def _sync_summary_visibility(self) -> None:
        self._summary.setVisible(bool(getattr(self, '_show_summary', not self._compact))
                                 and bool(self._summary.name))

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self._density = float(not compact)
        self._apply_metrics()

    def set_stage_layout(self, stage):
        self._compact = stage.compact
        self._density = stage.openness
        self._apply_metrics()

    def _apply_metrics(self) -> None:
        """按导航自己的可用宽度分配摘要与入口，避免依赖全屏宽度。"""
        compact = self._compact
        layout = NavigationLayout(self.width(), compact, len(self.buttons), self._density)
        self.setFixedHeight(layout.height)
        self._row.setSpacing(bounded(6 + 4 * self._density, 6, 10))
        side = bounded(10 + 6 * self._density, 10, 16)
        top = bounded(4 + 2 * self._density, 4, 6)
        self._row.setContentsMargins(side, top, side, top)
        for button in getattr(self, 'buttons', {}).values():
            button.set_density(self._density)
            button.setFixedHeight(layout.height - bounded(10 + 4 * self._density, 10, 14))
        self._show_summary = layout.show_summary
        self._summary.setFixedWidth(layout.summary_width)
        self._sync_summary_visibility()

    def resizeEvent(self, event):
        self._apply_metrics()
        super().resizeEvent(event)

    def set_current(self, title: str) -> None:
        button = self.buttons.get(title)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def set_motion_enabled(self, enabled):
        for button in self.buttons.values():
            button.set_motion_enabled(enabled)


class NavigationDock(QWidget):
    """窗口中的导航槽：居中停靠、外边距和宽度上限由组件统一负责。"""

    def __init__(self, navigation, parent=None):
        super().__init__(parent)
        self.navigation = navigation
        self._compact = False
        self._stage = None
        self._layout = QHBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        self._layout.addWidget(navigation)
        self._layout.addStretch(1)
        self.set_compact(False)

    def set_compact(self, compact):
        self._stage = None
        self._compact = bool(compact)
        self.navigation.set_compact(compact)
        self._apply_width()

    def set_stage_layout(self, stage):
        self._stage = stage
        self._compact = stage.compact
        self.navigation.set_stage_layout(stage)
        self._apply_width()

    def _apply_width(self):
        side = max(14, min(36, round(self.width() * .018)))
        bottom = self._stage.blend(10, 16) if self._stage else (10 if self._compact else 16)
        self._layout.setContentsMargins(side, 0, side, bottom)
        self.navigation.setFixedWidth(min(NavigationLayout.MAX_WIDTH, max(320, self.width() - 2 * side)))
        self.navigation._apply_metrics()
        self.setFixedHeight(self.navigation.height() + bottom)

    def resizeEvent(self, event):
        self._apply_width()
        super().resizeEvent(event)
