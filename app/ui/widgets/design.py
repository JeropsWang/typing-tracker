"""公共视觉组件：纸张容器、艺术标题、底部导航、字段与折叠区。

交接规格（design/spec.json）的颜色与尺寸只在这里集中定义，
页面通过语义角色取用，不在各自的组件里临时发明颜色或尺寸。

视觉配方出处：`tools/render_design.py`（生成全部设计稿的脚本）。
本文件里每条“配方”注释都标了该脚本的行号，取值照抄，不做比例改写：

* 纸张   第 82–96 行 `paper()`：**无圆角的直线毛边路径**，上边 `(i%3)*2`、
         下边 `(i%4)*1.5`，右边 +2、下边 −5，`Qt.NoPen` 不描边，下有墨影
         `#131622` 偏移 (4, 10) 圆角 10。
* 卡片   第 25–28 行 `box()`：大面积卡片一律 `stroke=None`（无描边），
         填充为同色系浅色（`#E1D8D0`/`#DED4CB`/`#2B2B3B`…），圆角 8/12/16。
* 底栏   第 113–131 行：`frames.nav` 几何 + 16px 圆角 + `#232430` 底，
         左端杯形图标 44 + 昵称 16px DemiBold + `Lv.N · 称号` 13px；
         选中项 = `#3B354C` 圆角底 + 加粗 + 玫瑰色 3px 下划线（三重表达）。
* 标题   第 31–37 行 `text()`：Microsoft YaHei UI，只有 Normal/DemiBold 两档，
         **脚本从未设置字距**（setLetterSpacing 全脚本 0 次）。

px 弹性（本轮新增）：`scale_factor()` 给出唯一的尺度系数，
间距/圆角/图标/纸张内外留白按它取上下限；**字号仍守 16/20/14/13/28/32**，
因为 UI_SPEC 第 7 行要求“紧凑窗口仍保持正文 16px，不能整体按图片缩放”。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)
from ..palette import P

from .visual_tokens import (
    TITLEBAR_HEIGHT, FIELD_HEIGHT, FIELD_HEIGHT_COMPACT, BUTTON_HEIGHT, BUTTON_HEIGHT_COMPACT,
    RADIUS, FOCUS_WIDTH, PAPER_PAD, PAPER_PAD_COMPACT, FONT_BODY,
    FONT_REFERENCE, FONT_LABEL, FONT_HELPER, FONT_PAGE_TITLE, FONT_METRIC,
    FONT_PAGE_TITLE_LARGE, FONT_METRIC_LARGE, NAV_HEIGHT, NAV_HEIGHT_COMPACT, ICON_SIZE,
    NAV_ICON_SIZE, NAV_ICON_SIZE_COMPACT, NAV_PILL_RADIUS, NAV_UNDERLINE_H, PAGE_MARGIN_X,
    PAGE_MARGIN_X_COMPACT, PAGE_MARGIN_TOP, PAGE_MARGIN_TOP_COMPACT, PAGE_MAX_WIDTH, PAGE_MAX_WIDTH_COMPACT,
    SCALE_BASE_W, SCALE_BASE_H, SCALE_MIN_W, SCALE_MIN_H, SCALE_MIN,
    SCALE_MAX, ASSETS, scale_factor, asset_path, is_compact,
    widget_scale, scale_px, field_height, button_height, paper_padding,
    page_gap, rgba, mix, is_dark_surface, card_fill,
    card_fill_soft, card_radius, nav_active_fill, nav_border_color, nav_underline_color,
    paper_ink_shadow, nav_height, nav_icon_size,
)
from .navigation import BottomNav, NavButton, nav_icon
from .responsive import stage_layout_for

# ---------- 补充素材包 v2：撕边纸张 / 四页转曲艺术标题 / 装饰贴纸 ----------
# 落位见素材包 START_HERE.md 第 21–23 行：`assets/` 内容对应复制到 `app/ui/assets/`，
# asset_root 指**包含 assets 子目录的目录**（这里是 app/ui/），避免拼出 assets/assets/。
DECKLE_PAPER = ('paper', 'deckle-paper.png')
#: catalog.json 第 15–17 行：实心纸面基准矩形（源图 1643×957）
DECKLE_BODY_RECT = (44.0, 63.0, 1559.0, 844.0)
#: 四页转曲艺术标题（catalog.json 第 25–86 行）+ 训练页原稿
LETTERING = {
    'today': ('lettering', 'today.svg'),
    'stats': ('lettering', 'stats.svg'),
    'growth': ('lettering', 'growth.svg'),
    'settings': ('lettering', 'settings.svg'),
    'training': ('lettering', 'training.svg'),
    'ai': ('lettering', 'ai.svg'),
}
LETTERING_TEXT = {
    'today': '今天的每一次敲击',
    'stats': '把进步慢慢看清',
    'growth': '小小坚持，大大成长',
    'settings': '把习惯调成喜欢的样子',
    'training': '今天也要 闪闪发光',
    'ai': '把灵感 敲成星光',
}
DECORATION_SIZES = {
    'star-gold': (24, 48), 'star-outline': (24, 48),
    'bow-rose': (24, 48), 'bow-violet': (24, 48),
    'tape-rose': (64, 100), 'tape-violet': (64, 100),
    'note-corner': (32, 48), 'note-corner-star': (32, 48),
}
DECORATION_NAMES = tuple(DECORATION_SIZES)


def lettering_path(role: str = 'training') -> Path:
    """取某个页面的转曲艺术标题路径；未知 role / 文件缺失时回退训练页原稿。

    回退链保证「没有对应资源的主题或页面不得崩、不得出现空框」：
    未知 role 一律回退 `lettering/training.svg`；只有当整棵 `lettering/` 都不在时
    才返回不存在的路径，此时 `ArtTitle.has_artwork()` 为 False → 不绘制也不占位。

    去重说明：`app/ui/assets/lettering.svg`（v1 的扁平文件）与
    `app/ui/assets/lettering/training.svg` 曾逐字节相同（SHA256
    `59234B402FEBECA9…`），是两条并行落位路径撞车。**统一保留目录形式**
    `lettering/<role>.svg`，扁平文件已删除（全仓 grep 确认没有任何代码按
    扁平路径引用它）。
    """
    for key in (role, 'training'):
        parts = LETTERING.get(key)
        if parts:
            path = asset_path(*parts)
            if path.exists():
                return path
    return asset_path(*LETTERING['training'])


class _PaperTexture:
    """交付的透明撕边纸张（`assets/paper/deckle-paper.png`）的绘制适配。

    用法完全照 `examples/qt_usage.py` 第 8–27 行：把 `bodyRect`（实心纸面）映射到
    目标纸张矩形，`bodyRect` 之外的透明毛边自然向外延伸，**不能**把整张图缩到
    控件范围内（那会把毛边压进纸面）。
    """

    def __init__(self, path: Path, body_rect):
        self.path = path
        self.body = QRectF(*body_rect)
        self.image = None
        self._tried = False

    def ensure(self) -> bool:
        if not self._tried:
            self._tried = True
            if self.path.exists():
                image = QImage(str(self.path))
                self.image = None if image.isNull() else image
        return self.image is not None

    def destination(self, target_body: QRectF) -> QRectF:
        """按 bodyRect → target_body 的等比映射算出整图绘制矩形（示例第 18–23 行）。"""
        if self.image is None or self.body.isEmpty():
            return QRectF()
        sx = target_body.width() / self.body.width()
        sy = target_body.height() / self.body.height()
        return QRectF(target_body.x() - self.body.x() * sx,
                      target_body.y() - self.body.y() * sy,
                      self.image.width() * sx,
                      self.image.height() * sy)

    def draw(self, painter: QPainter, target_body: QRectF) -> bool:
        if not self.ensure():
            return False
        dest = self.destination(target_body)
        if dest.isEmpty():
            return False
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawImage(dest, self.image)
        painter.restore()
        return True


_PAPER_TEXTURE = None


def paper_texture() -> _PaperTexture:
    """纸张纹理单例（懒加载 1643×957 的 PNG，只读一次）。"""
    global _PAPER_TEXTURE
    if _PAPER_TEXTURE is None:
        _PAPER_TEXTURE = _PaperTexture(asset_path(*DECKLE_PAPER), DECKLE_BODY_RECT)
    return _PAPER_TEXTURE


def has_paper_texture() -> bool:
    return paper_texture().ensure()


class PaperSurface(QFrame):
    """奶油纸张容器：交付的透明撕边 PNG 优先，缺失时回退自绘毛边路径。

    有纹理（`assets/paper/deckle-paper.png`）：按 `bodyRect` 映射，透明毛边向外
    延伸，纸张边界与控件矩形一致，纸内控件排版完全不受影响（START_HERE 第 25 行
    “preferredLogicalSize 不是要求图片恰好 1200×700”）。
    没纹理（主题/构建未带资源）：回退到配方 `render_design.py` 第 87–94 行的
    **纯 lineTo 无圆角毛边路径**，保证任何情况下都不出现空框。
    """

    #: 墨影相对纸张的偏移 (dx, dy) 与圆角，配方第 86 行（仅回退路径使用）
    SHADOW_DX, SHADOW_DY, SHADOW_RADIUS = 4, 10, 10

    def __init__(self, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self.setProperty('paperSurface', True)
        self.set_compact(compact)

    def set_compact(self, compact: bool) -> None:
        self.setProperty('paperCompact', bool(compact))
        pad = paper_padding(compact)
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(pad, pad, pad, pad)
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()

    @staticmethod
    def _paper_path(rect: QRectF) -> QPainterPath:
        """配方 `paper()`（render_design.py 第 87–94 行）的等价实现，**固定相位**。

        上边：24 段，`y + (i % 3) * 2`（振幅 0/2/4，周期 3）
        右边：直线到 `(x + w + 2, y + h - 5)`
        下边：25 点倒序，`y + h - (i % 4) * 1.5`（振幅 0/1.5/3/4.5，周期 4）
        """
        path = QPainterPath()
        x, y = rect.left(), rect.top()
        w, h = rect.width(), rect.height()
        path.moveTo(x, y + 4)
        for i in range(1, 25):
            path.lineTo(x + w * i / 24, y + (i % 3) * 2)
        path.lineTo(x + w + 2, y + h - 5)
        for i in range(24, -1, -1):
            path.lineTo(x + w * i / 24, y + h - (i % 4) * 1.5)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        # 交付纹理优先：透明撕边向外延伸，纸张边界 = 控件矩形
        if paper_texture().draw(painter, rect):
            painter.end()
            return
        # 回退：配方第 85–96 行（墨影 + 无描边毛边路径）
        dx, dy, radius = self.SHADOW_DX, self.SHADOW_DY, self.SHADOW_RADIUS
        shadow = QRectF(rect.left() + dx, rect.top() + dy, rect.width(), rect.height())
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(paper_ink_shadow()))
        painter.drawRoundedRect(shadow, radius, radius)
        painter.setBrush(QColor(P.paper))
        painter.drawPath(self._paper_path(rect))
        painter.end()


class Panel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty('designPanel', True)


class PaperPage(QWidget):
    """共用页面骨架：艺术页头、左侧纸张和滚动兜底，宽度与留白连续变化。

    业务内容加入 body，页头通过 set_header 设置；右侧保留人物插画空间。
    """

    def __init__(self, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self._compact = bool(compact)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        self._holder = QVBoxLayout(holder)
        self._holder.setSpacing(0)
        # 页头槽（纸张之外，画布上）：默认隐藏，不占高度
        self._header_wrap = QWidget()
        self.header = QVBoxLayout(self._header_wrap)
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setSpacing(6)
        self._header_wrap.setVisible(False)
        self._holder.addWidget(self._header_wrap)
        paper_row = QWidget()
        self._paper_row = QHBoxLayout(paper_row)
        self._paper_row.setContentsMargins(0, 0, 0, 0)
        self._paper_row.setSpacing(0)
        self.paper = PaperSurface(compact=compact)
        self.body = QVBoxLayout(self.paper)
        self.body.setSpacing(16)
        self._paper_row.addWidget(self.paper, 0, Qt.AlignTop | Qt.AlignLeft)
        self._paper_row.addStretch(1)
        self._holder.addWidget(paper_row)
        self._holder.addStretch(1)
        self.scroll.setWidget(holder)
        outer.addWidget(self.scroll)
        self._paper_w = 0
        self.set_compact(compact)

    def set_header(self, widget) -> None:
        """把页头（画布上的标题/说明）放进纸张之外的槽位；未调用则该区域完全不占高度。"""
        self.header.addWidget(widget)
        self._header_wrap.setVisible(True)
        self._header_wrap.setContentsMargins(0, 0, 0, 0)
        self._apply_header_gap()
        self._apply_width()

    def _apply_header_gap(self) -> None:
        stage = stage_layout_for(self)
        self.header.setContentsMargins(0, 0, 0, stage.blend(12, 24))
        self._header_wrap.setFixedHeight(stage.blend(138, 192))

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        self._compact = compact
        self.paper.set_compact(compact)
        stage = stage_layout_for(self)
        self._holder.setContentsMargins(
            stage.margin_x, stage.margin_top, stage.margin_x, 0)
        if self._header_wrap.isVisible():
            self._apply_header_gap()
        self._apply_width()

    def _apply_width(self) -> None:
        """共享连续宽度策略，宽屏继续增长，右侧保留人物插画区域。"""
        stage = stage_layout_for(self)
        self._holder.setContentsMargins(stage.margin_x, stage.margin_top, stage.margin_x, 0)
        width = stage.content_width
        if width != self._paper_w:
            self._paper_w = width
            self.paper.setFixedWidth(width)

    def resizeEvent(self, event):
        if getattr(self, '_paper_w', None) is not None:
            if self._header_wrap.isVisible():
                self._apply_header_gap()
            self._apply_width()
        super().resizeEvent(event)


class PageHeading(QWidget):
    def __init__(self, title, description='', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.title = QLabel(title)
        self.title.setProperty('textRole', 'heading')
        self.description = QLabel(description)
        self.description.setWordWrap(True)
        self.description.setProperty('textRole', 'muted')
        layout.addWidget(self.title)
        layout.addWidget(self.description)


class PaperHeading(QWidget):
    """纸张上的标题 + 说明（正文 16px，标题 28px）。"""

    def __init__(self, title, description='', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.title = QLabel(title)
        self.title.setProperty('textRole', 'paperTitle')
        layout.addWidget(self.title)
        self.description = QLabel(description)
        self.description.setWordWrap(True)
        self.description.setProperty('textRole', 'paperMuted')
        self.description.setVisible(bool(description))
        layout.addWidget(self.description)


class ArtTitle(QWidget):
    """交付的转曲艺术标题，按比例缩放，**不依赖接收方字体，也不是字段标签**。

    可指定资源：`ArtTitle(role='today')` 取 `assets/lettering/today.svg`
    （四页 today / stats / growth / settings + 训练页原稿 training，
    即 `lettering/<role>.svg` 目录形式）；也接受直接传完整相对路径。
    按 DECISIONS.md 第 5 行：按比例缩放 SVG，不强行使用 220px 高度，
    画布标题被替换时仍要保留可访问名称与正常文字副标题（见 `ArtHeading`）。
    """

    def __init__(self, parent=None, *, role: str = 'training', lettering: str = ''):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.role = role if not lettering else ''
        self._path = asset_path(lettering) if lettering else lettering_path(role)
        self._renderer = QSvgRenderer(str(self._path)) if self._path.exists() else None
        self._compact = False
        self.setMinimumHeight(90)
        if role in LETTERING_TEXT and not lettering:
            # 可访问名称：艺术字本身没有文本语义，读屏需要这个名字
            self.setAccessibleName(LETTERING_TEXT[role])

    def set_role(self, role: str) -> None:
        """切换艺术标题资源（页面复用自己的实例时用）；找不到资源则保持原样。"""
        path = lettering_path(role)
        if path == self._path and self._renderer is not None:
            return
        self.role = role
        self._path = path
        self._renderer = QSvgRenderer(str(path)) if path.exists() else None
        self.update()

    def set_compact(self, compact: bool) -> None:
        self._compact = bool(compact)
        self.setMinimumHeight(64 if compact else 120)
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt 命名)
        return QSize(650 if not self._compact else 415, 220 if not self._compact else 130)

    def has_artwork(self) -> bool:
        return self._renderer is not None and self._renderer.isValid()

    def paintEvent(self, event):
        if not self.has_artwork():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = self.rect()
        # 保持 650:220 比例居中绘制，紧凑窗口整体缩小但不改写正文
        target_w = box.width()
        target_h = int(target_w * 220 / 650)
        if target_h > box.height():
            target_h = box.height()
            target_w = int(target_h * 650 / 220)
        x = box.x() + (box.width() - target_w) // 2
        y = box.y() + (box.height() - target_h) // 2
        p.setOpacity(.78 + .22 * stage_layout_for(self).openness)
        self._renderer.render(p, QRectF(float(x), float(y), float(target_w), float(target_h)))
        p.end()


class ArtHeading(QWidget):
    """画布页头 = 转曲艺术标题 + 正常文字副标题（DECISIONS.md 第 5 行）。

    艺术字只做装饰层：可访问名称落在 `ArtTitle` 上，副标题仍是普通可读字体；
    资源缺失时不占位、不出现空框（`has_artwork()` 为 False 时隐藏艺术字行）。
    """

    def __init__(self, role: str, subtitle: str = '', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.art = ArtTitle(role=role, parent=self)
        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setWordWrap(True)
        self.subtitle.setProperty('textRole', 'muted')
        self.subtitle.setVisible(bool(subtitle))
        layout.addWidget(self.art, 0, Qt.AlignLeft)
        layout.addWidget(self.subtitle)
        self.art.setVisible(self.art.has_artwork())
        self._sync_art_size()

    def _sync_art_size(self) -> None:
        stage = stage_layout_for(self)
        self.art.set_compact(stage.compact)
        height = stage.blend(90, 130)
        width = min(max(1, self.width()), round(height * 650 / 220))
        self.art.setFixedSize(width, round(width * 220 / 650))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_art_size()


class Decoration(QWidget):
    """装饰贴纸（星 / 蝴蝶结 / 胶带 / 便签角标）叠加层。

    硬约束（DECISIONS.md 第 6 行）：
      * `Qt.WA_TransparentForMouseEvents` + `NoFocus`：不拦截点击、不可聚焦；
      * 作为独立叠加层由调用方定位，不进入任何会影响内容的布局；
      * 尺寸在 `DECORATION_SIZES` 的上下限内，未知名字/资源缺失一律不绘制也不占位。
    """

    def __init__(self, name: str, parent=None, *, size: int | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.name = name
        self._renderer = None
        path = asset_path('decorations', f'{name}.svg')
        if path.exists():
            renderer = QSvgRenderer(str(path))
            self._renderer = renderer if renderer.isValid() else None
        low, high = DECORATION_SIZES.get(name, (24, 48))
        side = high if size is None else max(low, min(high, int(size)))
        self.setFixedSize(side, side)
        self.setVisible(self._renderer is not None)

    def has_artwork(self) -> bool:
        return self._renderer is not None

    def paintEvent(self, event):
        if self._renderer is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._renderer.render(p, QRectF(self.rect()))
        p.end()


def decorate(parent, name: str, corner: str = 'top-right', *, margin: int = 12,
             size: int | None = None) -> Decoration:
    """把装饰贴纸挂到 `parent` 的某个角，并在 `parent` 尺寸变化时跟着走。

    只贴**角**（`DECISIONS.md` 第 6 行“优先贴纸角或页头”），因此不会压到
    居中排版的正文与刻度；仍然保持不拦截鼠标。
    """
    widget = Decoration(name, parent, size=size)
    widget.setProperty('decorCorner', corner)
    widget.setProperty('decorMargin', int(margin))

    def reposition(*_):
        m = int(widget.property('decorMargin') or 12)
        w, h = widget.width(), widget.height()
        x = parent.width() - w - m if 'right' in corner else m
        y = parent.height() - h - m if 'bottom' in corner else m
        widget.move(max(0, x), max(0, y))
        widget.raise_()

    widget.reposition = reposition          # 供调用方在布局变化后手动触发
    parent.installEventFilter(_DecorFilter(widget, reposition))
    reposition()
    return widget


class _DecorFilter(QObject):
    """内部事件过滤器：父控件 resize 时把贴纸重新贴角。"""

    def __init__(self, widget, callback):
        super().__init__(widget)
        self._callback = callback

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Resize:
            self._callback()
        return False


class Field(QWidget):
    def __init__(self, title, control, hint='', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.label = QLabel(title)
        self.label.setProperty('textRole', 'field')
        self.label.setBuddy(control)
        control.setAccessibleName(title)
        if hint:
            control.setAccessibleDescription(hint)
        layout.addWidget(self.label)
        layout.addWidget(control)
        if hint:
            helper = QLabel(hint)
            helper.setWordWrap(True)
            helper.setProperty('textRole', 'muted')
            layout.addWidget(helper)


class PaperField(QWidget):
    """纸张上的字段：可见标签 + 控件（不用占位文本代替字段标签）。"""

    def __init__(self, title, control, hint='', parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.label = QLabel(title)
        self.label.setProperty('textRole', 'paperField')
        self.label.setBuddy(control)
        control.setAccessibleName(title)
        if hint:
            control.setAccessibleDescription(hint)
        layout.addWidget(self.label)
        layout.addWidget(control)
        if hint:
            helper = QLabel(hint)
            helper.setWordWrap(True)
            helper.setProperty('textRole', 'paperMuted')
            layout.addWidget(helper)


class Disclosure(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._title = title
        self._label = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.toggle = QPushButton(title + ' · 展开')
        self.toggle.setCheckable(True)
        self.toggle.setProperty('buttonRole', 'quiet')
        self.body = QWidget()
        self.body.setVisible(False)
        self.content = QVBoxLayout(self.body)
        self.content.setContentsMargins(0, 0, 0, 0)
        self.toggle.toggled.connect(self._toggle)
        layout.addWidget(self.toggle, 0, Qt.AlignLeft)
        layout.addWidget(self.body)

    def _toggle(self, expanded):
        self.body.setVisible(expanded)
        self.toggle.setText(self._label + (' · 收起' if expanded else ' · 展开'))

    def detach_toggle(self, label: str = ''):
        """把折叠入口从竖向布局里摘出来，供页面把入口放进单行条（设计稿的次级条）。"""
        if label:
            self._label = label
        self.toggle.setParent(None)
        self.toggle.setText(self._label + (' · 收起' if self.toggle.isChecked() else ' · 展开'))
        return self.toggle

    def set_toggle_label(self, label: str) -> None:
        self._label = label
        self.toggle.setText(label + (' · 收起' if self.toggle.isChecked() else ' · 展开'))


class StageArt(QWidget):
    """（保留占位）上一轮自绘星形/蝴蝶结装饰，已被交付插画取代，当前无引用。

    保留空实现以免外部代码 `from ... import StageArt` 报错；新代码请使用
    `background.png` 插画 + `ArtTitle`/`ArtHeading` 艺术字 + `Decoration` 贴纸，
    不要再自绘装饰形状。（配方里也没有星星/蝴蝶结的界面图元：唯一的自绘装饰在
    `make_lettering()` 里，最终落成 `lettering/training.svg`。）
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedSize(0, 0)


def theme_qss():
    """语义选择器只作用于组件自身，避免父面板样式污染子控件。

    去硬边约定（本轮）：卡片（`designPanel`）**不描边**，底栏与标题栏也不出现
    深色 1px 硬框；**只保留键盘焦点的 2px 轮廓**（无障碍要求，且
    `scripts/test_ui_workflow.py` 会断言 `2px solid {P.focus}` 存在）。
    """
    return f'''
    QWidget {{ font-family: "Microsoft YaHei UI"; font-size: {FONT_BODY}px; }}
    /* 卡片：同色系浅填充 + 大圆角 + 无描边（配方 box(stroke=None)，第 25–28 行） */
    QFrame[designPanel="true"] {{
        background: {card_fill()}; border: none; border-radius: 16px; }}
    /* 纸张形状由 PaperSurface.paintEvent 自绘；QSS 不能再画圆角矩形 */
    QFrame[paperSurface="true"] {{ background: transparent; border: none; }}
    QLabel[textRole="heading"] {{ color: {P.surface_text}; font-size: 23px; font-weight: 600; }}
    QLabel[textRole="muted"] {{ color: {P.surface_muted}; font-size: {FONT_HELPER}px; }}
    QLabel[textRole="field"] {{ color: {P.surface_text}; font-weight: 600; font-size: {FONT_LABEL}px; }}
    QLabel[textRole="paperTitle"] {{ color: {P.paper_text}; font-size: {FONT_PAGE_TITLE}px; font-weight: 600; }}
    QLabel[textRole="paperField"] {{ color: {P.paper_text}; font-weight: 600; font-size: {FONT_LABEL}px; }}
    QLabel[textRole="paperMuted"] {{ color: {P.paper_muted}; font-size: {FONT_HELPER}px; }}
    QLabel[textRole="paperMetric"] {{ color: {P.paper_text}; font-size: {FONT_METRIC}px; font-weight: 700; }}
    QLabel[textRole="paperSuccess"] {{ color: {P.success_on_paper}; font-size: {FONT_HELPER}px; }}
    QLabel[textRole="paperDanger"] {{ color: {P.danger_on_paper}; font-size: {FONT_HELPER}px; }}
    QPushButton {{ min-height: 26px; padding: 7px 14px; border-radius: 10px; }}
    QPushButton[buttonRole="primary"] {{ background: {P.primary}; color: {P.primary_text}; border: none; font-weight: 600; }}
    QPushButton[buttonRole="primary"]:hover {{ background: {mix(P.primary, P.paper_text, 0.86)}; color: {P.primary_text}; border: none; }}
    QPushButton[buttonRole="primary"]:disabled {{ background: {mix(P.primary, P.surface, 0.45)}; color: {P.surface_muted}; border: none; }}
    QPushButton[buttonRole="quiet"] {{ background: transparent; color: {P.surface_muted}; border: none; }}
    QPushButton[buttonRole="quiet"]:hover {{ color: {P.surface_text}; background: {card_fill_soft()}; }}
    QFrame[paperSurface="true"] QPushButton[buttonRole="primary"] {{
        background: {P.primary}; color: {P.primary_text}; border: none;
        border-radius: 22px; padding: 0 18px;
        font-size: {FONT_BODY}px; font-weight: 600; }}
    QFrame[paperSurface="true"] QPushButton[buttonRole="primary"]:disabled {{
        background: {rgba(P.primary, 0.30)}; color: {P.paper_text}; border: none; }}
    QFrame[paperSurface="true"] QPushButton[buttonRole="quiet"] {{ color: {P.paper_muted};
        padding: 2px 6px; min-height: 0px; }}
    QFrame[paperSurface="true"] QPushButton[buttonRole="quiet"]:hover {{ color: {P.paper_text}; background: rgba(255,255,255,0.55); }}
    QFrame[paperSurface="true"] QPushButton[buttonRole="secondary"] {{
        background: {rgba(P.primary, 0.62)}; color: {P.primary_text}; border: none;
        border-radius: 22px; padding: 0 18px; font-weight: 600; }}
    QFrame[paperSurface="true"] QPushButton[buttonRole="secondary"]:hover {{ background: {rgba(P.primary, 0.82)}; }}
    QFrame[paperSurface="true"] QPushButton[buttonRole="secondary"]:disabled {{
        background: {rgba(P.primary, 0.26)}; color: {P.paper_text}; }}
    QFrame[paperSurface="true"] QPushButton[growthTab="true"] {{
        background: {rgba(P.primary, 0.28)}; color: {P.paper_text}; border: none;
        border-radius: {RADIUS}px; padding: 6px 26px; font-size: {FONT_BODY}px; }}
    QFrame[paperSurface="true"] QPushButton[growthTab="true"]:checked {{
        background: {rgba(P.primary, 0.62)}; color: {P.primary_text}; font-weight: 600; }}
    QFrame[paperSurface="true"] QPushButton[growthTab="true"]:hover {{ background: {rgba(P.primary, 0.45)}; }}
    QFrame[paperSurface="true"] QPushButton[growthTab="true"]:focus {{
        border: {FOCUS_WIDTH}px solid {P.focus_on_paper}; }}
    QFrame[paperSurface="true"] QLabel {{ color: {P.paper_text}; }}
    /* 焦点轮廓：全仓唯一的“描边”来源，2px，无障碍必需 */
    QPushButton:focus, QLineEdit:focus, QPlainTextEdit:focus, QTextBrowser:focus, QComboBox:focus, QSpinBox:focus {{ border: {FOCUS_WIDTH}px solid {P.focus}; }}
    QFrame[paperSurface="true"] QPushButton:focus, QFrame[paperSurface="true"] QLineEdit:focus,
    QFrame[paperSurface="true"] QPlainTextEdit:focus, QFrame[paperSurface="true"] QTextBrowser:focus,
    QFrame[paperSurface="true"] QComboBox:focus, QFrame[paperSurface="true"] QSpinBox:focus {{
        border: {FOCUS_WIDTH}px solid {P.focus_on_paper}; }}
    QLineEdit, QComboBox, QSpinBox {{ min-height: 26px; padding: 7px 10px; }}
    /* 输入类：配方仍保留 1px 描边（第 150/183/288 行），但改成同色系淡描边 */
    QFrame[paperSurface="true"] QComboBox, QFrame[paperSurface="true"] QSpinBox,
    QFrame[paperSurface="true"] QLineEdit {{
        background: rgba(255, 255, 255, 0.75); color: {P.paper_text};
        border: 1px solid {rgba(P.paper_text, 0.18)}; border-radius: {RADIUS}px;
        min-height: {FIELD_HEIGHT - 20}px; padding: 8px 12px; font-size: {FONT_BODY}px; }}
    QFrame[paperSurface="true"] QPlainTextEdit, QFrame[paperSurface="true"] QTextBrowser {{
        background: rgba(255, 255, 255, 0.75); color: {P.paper_text};
        border: 1px solid {rgba(P.paper_text, 0.18)}; border-radius: {RADIUS}px;
        padding: 12px; font-size: {FONT_REFERENCE}px; selection-background-color: {P.primary};
        selection-color: {P.primary_text}; }}
    QFrame[paperSurface="true"] QComboBox::drop-down {{ border: none; width: 24px; }}
    QFrame[paperSurface="true"] QComboBox::down-arrow {{ image: url("{asset_path('nav', 'chevron-ink.svg').as_posix()}"); width:12px; height:12px; }}
    QFrame[paperSurface="true"] QComboBox QAbstractItemView {{
        background: {P.paper}; color: {P.paper_text}; border: 1px solid {rgba(P.paper_text, 0.18)};
        font-size: {FONT_REFERENCE}px;
        selection-background-color: {P.primary}; selection-color: {P.primary_text}; }}
    QPushButton[buttonRole="entry"] {{ background: transparent; border: none;
        color: {P.surface_muted}; padding: 2px 8px; min-height: 40px; max-height: 40px; font-size: {FONT_HELPER}px; }}
    QPushButton[buttonRole="entry"]:hover {{ color: {P.surface_text}; }}
    QPushButton[buttonRole="entry"]:checked {{ color: {P.surface_text}; font-weight: 600; }}
    QPushButton[buttonRole="entry"]:focus {{ border: {FOCUS_WIDTH}px solid {P.focus}; }}
    /* 底栏项：外观全部由 NavButton.paintEvent 自绘，QSS 只留焦点轮廓 */
    QPushButton[navItem="true"] {{ background: transparent; border: none;
        padding: 0px; color: {P.surface_text}; font-size: {FONT_BODY}px; border-radius: {NAV_PILL_RADIUS}px; }}
    QPushButton[navItem="true"]:hover {{ background: transparent; border: none; }}
    QPushButton[navItem="true"]:checked {{ background: transparent; border: none; }}
    QPushButton[navItem="true"]:disabled {{ color: {P.surface_muted}; }}
    QPushButton[navItem="true"]:focus {{ border: {FOCUS_WIDTH}px solid {P.focus}; }}
    QLabel[textRole="navSummary"] {{ color: {P.surface_text}; font-size: {FONT_BODY}px; font-weight: 600; }}
    QLabel[textRole="navSummaryMuted"] {{ color: {P.surface_muted}; font-size: {FONT_HELPER}px; }}
    /* 浮起的底栏：与配方同几何，描边改成同色系近不可见，不留深色硬框 */
    QWidget#bottomNav {{ background: {P.surface}; border-radius: 30px;
        border: 1px solid {nav_border_color()}; }}
    QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
    '''
