"""公共视觉尺寸与颜色规则，不包含页面或导航实现。"""
from pathlib import Path
from PySide6.QtGui import QColor
from ..palette import P

# ---------- spec.json 尺寸 token（Qt 逻辑像素） ----------
TITLEBAR_HEIGHT = 42
FIELD_HEIGHT = 44
FIELD_HEIGHT_COMPACT = 40
BUTTON_HEIGHT = 52
BUTTON_HEIGHT_COMPACT = 44
RADIUS = 12
FOCUS_WIDTH = 2
PAPER_PAD = 32
PAPER_PAD_COMPACT = 20
FONT_BODY = 16
FONT_REFERENCE = 20
FONT_LABEL = 14
FONT_HELPER = 13
FONT_PAGE_TITLE = 28
FONT_METRIC = 32
# 配方实测：设计稿的页面标题画的是 36px（render_design.py 第 225 行），
# spec.json 第 12 行的名义 token 是 28px；两者都留着，页面按需取用。
FONT_PAGE_TITLE_LARGE = 36
FONT_METRIC_LARGE = 82          # render_design.py 第 231 行的大数字
NAV_HEIGHT = 92                 # frames.nav[3]，layout_conformance 按此核对
NAV_HEIGHT_COMPACT = 62
ICON_SIZE = 26                  # 章节/字段处的通用小图标（非导航）
NAV_ICON_SIZE = 42              # 配方第 128 行：底栏图标 42×42
NAV_ICON_SIZE_COMPACT = 29      # 配方第 133 行：紧凑底栏图标 29×29
NAV_PILL_RADIUS = 14            # 配方第 127 行
NAV_UNDERLINE_H = 3             # 配方第 131 行
# 页面骨架：纸张靠左、右侧留给交付插画（设计稿各页一致）
PAGE_MARGIN_X, PAGE_MARGIN_X_COMPACT = 48, 24
PAGE_MARGIN_TOP, PAGE_MARGIN_TOP_COMPACT = 44, 16
PAGE_MAX_WIDTH, PAGE_MAX_WIDTH_COMPACT = 1100, 760

# 尺度系数的基准与上下限（UI_SPEC 第 26 行：基准稿 1440×1024 / 900×640）
SCALE_BASE_W, SCALE_BASE_H = 1440, 1024
SCALE_MIN_W, SCALE_MIN_H = 900, 640
SCALE_MIN, SCALE_MAX = 0.85, 1.15

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def scale_factor(width: int, height: int) -> float:
    """唯一的尺寸尺度系数：以尺度系数自身的上下限为端点，宽度主导、高度只做降档。

    直接 `clamp(min(w/1440, h/1024), 0.85, 1.15)` 会让 1200×800（0.78）、
    1100×900（0.76）等等全被同一个下限吃掉 → 900…1439 宽之间底栏/间距一模一样，
    这正是“px 死板”的另一面。这里改成为：

        s   = 0.85 + 0.15 · (w - 900) / (1440 - 900)      # 宽度 → 0.85…1.00
        s  *= min(1, 0.5 + 0.5 · h / 1024)                # 高度不足时再降一档
        s   = clamp(s, 0.85, 1.15)

    两个基准分毫不差：1440×1024 → 0.85 + 0.15·1.0 = 1.000（×1.0）；
    900×640 → 0.85 + 0 = 0.850（×0.8125，被下限兜住）。1200×800 → 0.933
    （×0.89 = 0.830 → 下限 0.85，但 1280×900 → 0.956）、1600×1000 → 1.017。
    **不作用于字号**（UI_SPEC 第 7 行：紧凑窗口仍保持正文 16px）。
    """
    if width <= 0 or height <= 0:
        return SCALE_MIN
    span = (SCALE_BASE_W - SCALE_MIN_W) or 1
    raw = SCALE_MIN + (1.0 - SCALE_MIN) * (width - SCALE_MIN_W) / span
    raw *= min(1.0, 0.5 + 0.5 * height / SCALE_BASE_H)
    return max(SCALE_MIN, min(SCALE_MAX, raw))


def asset_path(*parts) -> Path:
    return ASSETS.joinpath(*parts)


def is_compact(width: int, height: int) -> bool:
    """900x640 基准以下算紧凑窗口：控件高度与内边距降级，字号不缩。"""
    return width <= 1000 or height <= 720


def widget_scale(widget) -> float:
    """取某个控件的尺度系数；拿不到尺寸时退回最小档。"""
    if widget is None:
        return SCALE_MIN
    width = widget.width()
    height = widget.height()
    window = widget.window() if hasattr(widget, 'window') else None
    if window is not None and window is not widget:
        # 优先用顶层窗口，保证同一窗口内所有尺度一致
        if window.width() > 0 and window.height() > 0:
            return scale_factor(window.width(), window.height())
    return scale_factor(width, height)


def scale_px(value: float, scale: float, *, minimum: int = 0) -> int:
    """按尺度系数取整缩放一个尺寸；`minimum` 给下限，避免小窗口压到不可用。"""
    return max(minimum, int(round(value * scale)))


def field_height(compact: bool = False) -> int:
    return FIELD_HEIGHT_COMPACT if compact else FIELD_HEIGHT


def button_height(compact: bool = False) -> int:
    return BUTTON_HEIGHT_COMPACT if compact else BUTTON_HEIGHT


def paper_padding(compact: bool = False) -> int:
    """纸张内边距（配方/UI_SPEC 第 17 行：32，紧凑 20）。**基准值，不随窗口缩放**。"""
    return PAPER_PAD_COMPACT if compact else PAPER_PAD


def page_gap(scale: float) -> int:
    """页头与纸张之间的间距：紧凑基准 16、常规基准 24，按 scale 弹性。"""
    return scale_px(16, scale, minimum=12)


def rgba(color: str, alpha: float) -> str:
    """把主题色转成 QSS 可用的 rgba()（主题色是十六进制字符串）。"""
    c = QColor(color)
    return f'rgba({c.red()}, {c.green()}, {c.blue()}, {max(0, min(255, int(alpha * 255)))})'


def mix(color_a: str, color_b: str, weight_a: float) -> str:
    """按权重混合两个颜色（与 palette.mix 同口径，供同色系派生用）。

    `color_a` 占比 `weight_a`；任一侧带 alpha（`#AARRGGBB`/`rgba(...)`）时
    原样返回 `color_a`，避免把半透明色混成实色。
    """
    def parts(value: str):
        value = value.strip()
        if value.startswith('rgba') or value.startswith('qlinear'):
            raise ValueError(value)
        value = value.lstrip('#')
        if len(value) == 8:            # #AARRGGBB
            raise ValueError(value)
        if len(value) != 6:
            raise ValueError(value)
        return [int(value[i:i + 2], 16) for i in (0, 2, 4)]

    try:
        a, b = parts(color_a), parts(color_b)
    except (ValueError, IndexError):
        return color_a
    out = [round(a[i] * weight_a + b[i] * (1 - weight_a)) for i in range(3)]
    return '#%02X%02X%02X' % tuple(max(0, min(255, c)) for c in out)


def is_dark_surface(color: str) -> bool:
    """判断一个颜色是否偏暗（决定同色系浅填充往哪个方向派生）。"""
    c = QColor(color)
    if not c.isValid():
        return True
    channels = [c.red() / 255, c.green() / 255, c.blue() / 255]
    linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in channels]
    return (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]) < 0.35


def card_fill() -> str:
    """卡片填充：同色系浅填充（配方第 233/247 行的 `#E1D8D0` 之于纸张的同一手法）。

    暗表面往文字色靠、亮表面往背景色靠，保证 `P.surface_text` 在其上仍有对比度。
    """
    base = P.surface
    toward = P.surface_text if is_dark_surface(base) else P.background
    return mix(base, toward, 0.88)


def card_fill_soft() -> str:
    """更浅的一档卡片填充（用于次级条 / 折叠区容器）。"""
    base = P.surface
    toward = P.surface_text if is_dark_surface(base) else P.background
    return mix(base, toward, 0.94)


def card_radius(scale: float = 1.0) -> int:
    """卡片圆角：配方 12（纸面浅卡）/16（深色卡），按 scale 弹性，下限 10。"""
    return scale_px(16, scale, minimum=10)


def nav_active_fill() -> str:
    """底栏选中项沿用紫灰色调，配合字重与下划线表达选中。"""
    return mix(P.surface, P.primary, 0.65)


def nav_border_color() -> str:
    """底栏描边：配方第 115 行 `#5B5669` 之于 `#232430` 仅 2.18:1，属于“碍眼硬边”。

    改成同色系、几乎不可见的 1px（往 surfaceText 偏 8%），保留配方“浮起”的分层感
    但不产生深色硬框；选中态的三重表达不依赖这条边。
    """
    return mix(P.surface, P.surface_text, 0.92)


def nav_underline_color() -> str:
    """选中下划线：配方第 131 行用玫瑰色，但要保证在任意主题下都能看见。"""
    rose = QColor(P.accent_rose)
    surface = QColor(P.surface)
    rose_lum = 0.2126 * rose.redF() + 0.7152 * rose.greenF() + 0.0722 * rose.blueF()
    surf_lum = 0.2126 * surface.redF() + 0.7152 * surface.greenF() + 0.0722 * surface.blueF()
    if abs(rose_lum - surf_lum) < 0.22:
        return P.surface_text
    return P.accent_rose


def paper_ink_shadow() -> str:
    """纸张墨影色：配方第 85 行 `#131622`，向画布混一点避免死黑。"""
    return mix(P.canvas, '#131622', 0.62)


def nav_height(scale: float, compact: bool) -> int:
    """底栏高度：紧凑基准 62、常规基准 92，中间尺寸**连续插值**。

    设计稿只有 `frames.nav` 的 92（1440×1024）与 62（900×640）两档。
    `scale` 在两个基准上分别是 0.85 / 1.00，所以 1440×1024 恰好得到 92、
    900×640 恰好得到 62；1200×800 这类中间尺寸（scale 仍受高度限制）得到 78，
    不再出现 1000/1001px 处 30px 的跳变。紧凑档以低于设计基准为界，
    所以 900×640 严格落在 62，满足既有核对。
    """
    if compact:
        span = max(0.0, min(1.0, (scale - SCALE_MIN) / (1.0 - SCALE_MIN)))
        return int(round(NAV_HEIGHT_COMPACT + span * (NAV_HEIGHT - NAV_HEIGHT_COMPACT)))
    return NAV_HEIGHT


def nav_icon_size(compact: bool) -> int:
    """底栏图标：配方第 128/133 行的 42 / 29。"""
    return NAV_ICON_SIZE_COMPACT if compact else NAV_ICON_SIZE
