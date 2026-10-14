"""Shared companion stationery, colour roles and small vector ornaments."""
from dataclasses import dataclass, replace
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QLinearGradient, QPen
from PySide6.QtWidgets import QDialog
from ..palette import P, mix


@dataclass(frozen=True)
class AgentColors:
    """智能体纸张、文字、边线及章节强调色的不可变颜色角色集合。"""
    bg: str
    surface: str
    ink: str
    muted: str
    line: str
    lavender: str
    blue: str
    coral: str
    accent: str
    on_accent: str

    @property
    def control_line(self):
        """混合强调色与纸张色得到输入控件边线，保持不同章节的层次和对比。"""
        return mix(self.accent, self.surface, .72)


def colors():
    # The application's dark canvas also has light paper. Follow the paper role.
    """依据实际纸张明暗返回智能体色板，避免把深色背景误判为深色纸张。"""
    if QColor(P.paper).lightnessF() < .45:
        return AgentColors('#282535', '#322e40', '#f5edf9', '#c0b4ce', '#6c5c80',
                           '#443751', '#2d4854', '#553941', '#cbb2ee', '#282033')
    return AgentColors('#f7f3fb', '#fffdfb', '#393247', '#6d5e79', '#d7cee3',
                       '#eee5fa', '#e2f3f7', '#ffe9e3', '#70558f', '#ffffff')


def settings_colors(section=0):
    """从共享色板派生模型/搜索/未来章节色，统一背景、边线与强调色。"""
    c = colors()
    dark = QColor(c.surface).lightnessF() < .45
    tone, accent = ((c.lavender, c.accent),
                    (c.blue, '#a8dbe5' if dark else '#356777'),
                    (c.coral, '#f0b5a8' if dark else '#925557'))[section]
    return replace(c, bg=mix(tone, c.bg, .32), accent=accent,
                   line=mix(accent, c.surface, .25))


def agent_style(palette=None):
    """生成原生 Widgets 共用样式表，可传入章节色板统一浮层与配置控件。"""
    c = palette or colors()
    return f'''
    QWidget {{font-family:"Microsoft YaHei UI";font-size:14px;color:{c.ink};}}
    QDialog {{background:{c.bg};}}
    QDialog#agentBubble, QWidget#companionAgentActions {{background:transparent;border:0;}}
    QLabel {{background:transparent;border:0;padding:0;}}
    QLabel[agentMuted="true"] {{color:{c.muted};font-size:12px;}}
    QLabel[agentHeading="true"] {{font-size:24px;font-weight:700;}}
    QLabel[agentEyebrow="true"] {{color:{c.accent};font-size:11px;font-weight:600;letter-spacing:2px;}}
    QLabel[agentBadge="true"] {{background:{c.lavender};color:{c.accent};border-radius:10px;padding:5px 9px;font-size:12px;}}
    QFrame[agentPanel="true"] {{background:{c.surface};border:1px solid {c.line};border-radius:18px;}}
    QFrame[agentTone="lavender"] {{background:{c.lavender};border:0;border-radius:18px;}}
    QFrame[agentTone="blue"] {{background:{c.blue};border:0;border-radius:18px;}}
    QFrame[agentTone="coral"] {{background:{c.coral};border:0;border-radius:18px;}}
    QLineEdit, QComboBox {{background:{c.surface};color:{c.ink};border:1px solid {c.control_line};border-radius:12px;padding:8px 10px;min-height:24px;selection-background-color:{c.accent};selection-color:{c.on_accent};}}
    QComboBox::drop-down {{border:0;width:24px;}}
    QComboBox QAbstractItemView {{background:{c.surface};color:{c.ink};selection-background-color:{c.lavender};selection-color:{c.ink};}}
    QPlainTextEdit, QTextBrowser {{background:transparent;color:{c.ink};border:0;font-size:15px;padding:0;selection-background-color:{c.lavender};}}
    QPushButton, QToolButton {{background:{c.surface};color:{c.ink};border:1px solid {c.line};border-radius:12px;padding:8px 14px;min-height:24px;}}
    QPushButton:hover, QToolButton:hover {{background:{c.lavender};border-color:{c.accent};}}
    QPushButton:pressed, QToolButton:pressed {{background:{c.blue};}}
    QPushButton[agentPrimary="true"] {{background:{c.accent};color:{c.on_accent};border-color:{c.accent};font-weight:600;}}
    QPushButton[agentPrimary="true"]:hover {{background:{c.ink};border-color:{c.ink};}}
    QPushButton[agentQuiet="true"], QToolButton[agentQuiet="true"] {{background:transparent;border:1px solid transparent;padding:6px 8px;}}
    QToolButton[agentQuiet="true"] {{padding:0;min-height:0;min-width:0;border-radius:10px;}}
    QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus, QTabBar::tab:focus {{border:2px solid {c.accent};}}
    QPushButton:disabled, QToolButton:disabled {{background:{c.bg};color:{c.muted};border-color:{c.line};}}
    QCheckBox {{background:transparent;spacing:8px;}}
    QCheckBox::indicator {{width:18px;height:18px;border:1px solid {c.accent};border-radius:6px;background:{c.surface};}}
    QCheckBox::indicator:checked {{background:{c.accent};}}
    QCheckBox:focus {{color:{c.accent};}}
    QScrollArea, QScrollArea > QWidget > QWidget {{background:transparent;border:0;}}
    QTabWidget::pane {{background:transparent;border:0;}}
    QTabBar::tab {{background:transparent;color:{c.muted};padding:10px 15px;margin:0 4px 8px 0;border:1px solid transparent;border-radius:12px;}}
    QTabBar::tab:selected {{background:{c.lavender};color:{c.accent};font-weight:600;border-color:{c.line};}}
    QTabBar::tab:hover {{background:{c.blue};color:{c.ink};}}
    QScrollBar:vertical {{background:transparent;width:6px;margin:3px 0;}}
    QScrollBar::handle:vertical {{background:{c.line};min-height:24px;border-radius:3px;}}
    QScrollBar::handle:vertical:hover {{background:{c.accent};}}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{height:0;}}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{background:transparent;}}
    '''


def sparkle(painter, center, radius, color):
    """在指定中心和半径绘制四角星装饰，只改变绘制状态，不接收鼠标。"""
    x, y = center.x(), center.y()
    path = QPainterPath(QPointF(x, y - radius))
    path.quadTo(x + radius * .18, y - radius * .18, x + radius, y)
    path.quadTo(x + radius * .18, y + radius * .18, x, y + radius)
    path.quadTo(x - radius * .18, y + radius * .18, x - radius, y)
    path.quadTo(x - radius * .18, y - radius * .18, x, y - radius)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPath(path)


class AgentBubble(QDialog):
    """Painted, asymmetric paper with a movable tail pointing at its companion."""
    def __init__(self, *, passive=False):
        """建立置顶透明纸张浮层；被动卡片显示时不抢夺用户焦点。"""
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName('agentBubble')
        self.setAttribute(Qt.WA_TranslucentBackground)
        if passive:
            self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.tail_on_top = False
        self.tail_x = 110
        self._anchor = None
        self.setStyleSheet(agent_style())

    def set_anchor(self, point):
        """记录桌宠的屏幕锚点，并更新纸张尾巴位置及方向。"""
        self._anchor = point
        self._update_anchor()
        self.update()

    def _update_anchor(self):
        """把全球锚点转为窗口坐标，将尾巴限制在安全边距并选择上/下边缘。"""
        if self._anchor is None:
            return
        local = self.mapFromGlobal(self._anchor)
        self.tail_x = max(48, min(self.width() - 58, local.x()))
        self.tail_on_top = local.y() < self.height() / 2

    def paintEvent(self, event):
        """绘制错位衬纸、非对称正文纸面、指向桌宠的尾巴与静态装饰。"""
        self._update_anchor()
        c = colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(9, 15, self.width() - 27, self.height() - 39)
        # A skewed second sheet provides depth without rotating readable content.
        p.save()
        p.translate(r.center())
        p.rotate(-3.2)
        p.translate(-r.center())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c.lavender))
        p.drawRoundedRect(r.translated(8, 7), 27, 27)
        p.restore()
        path = QPainterPath(QPointF(r.left() + 40, r.top()))
        if self.tail_on_top:
            path.lineTo(self.tail_x - 10, r.top())
            path.quadTo(self.tail_x - 2, r.top() - 2, self.tail_x + 8, 3)
            path.lineTo(self.tail_x + 13, r.top())
        path.lineTo(r.right() - 14, r.top())
        path.quadTo(r.right(), r.top(), r.right(), r.top() + 14)
        path.lineTo(r.right(), r.bottom() - 52)
        path.quadTo(r.right(), r.bottom(), r.right() - 52, r.bottom())
        if not self.tail_on_top:
            path.lineTo(self.tail_x + 18, r.bottom())
            path.quadTo(self.tail_x + 10, r.bottom() + 12, self.tail_x - 8, r.bottom() + 17)
            path.lineTo(self.tail_x - 6, r.bottom())
        path.lineTo(r.left() + 22, r.bottom())
        path.quadTo(r.left(), r.bottom(), r.left(), r.bottom() - 22)
        path.lineTo(r.left(), r.top() + 40)
        path.quadTo(r.left(), r.top(), r.left() + 40, r.top())
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0, QColor(c.surface))
        grad.setColorAt(1, QColor(c.bg))
        p.setPen(QPen(QColor(c.line), 1))
        p.setBrush(grad)
        p.drawPath(path)
        # A small tilted tape tab and a star are shared by input and report cards.
        p.save()
        p.translate(37, 17)
        p.rotate(-7)
        tape = QColor(c.blue)
        tape.setAlpha(225)
        p.setBrush(tape)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, -6, 46, 13), 3, 3)
        p.restore()
        sparkle(p, QPointF(self.width() - 25, self.height() - 31), 9, c.accent)
