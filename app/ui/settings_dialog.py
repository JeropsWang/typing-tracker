"""分组设置对话框：奶油纸张承载六组草稿表单、左侧分组、右侧滚动、底部固定操作栏。

设计基准 `.local/ui-night-stage/deepseek-handoff/v1/design/settings-dialog-820.png`（820×640，
固定 820×640）。分组名称与顺序严格沿用规格：个人资料/统计规则/应用排除/AI配置/外观/数据备份。

本模块的边界（不改业务）：
- 校验与提交继续走 `app.services.settings_service`，UI 不写 SQL；
- 连接测试仍用 `ConnectionTest` + `AIService`，只读草稿快照、不落库、不阻塞主线程；
- 颜色/尺寸取自 `app.ui.palette.P` 与 `app.ui.widgets.design`，不在本文件另立设计 token；
- 对比度兜底（`_readable`）只用于极少数既不提供纸张语义色、又给出深色画布的主题，
  保证纸面正文/辅助文字仍 ≥4.5:1。
"""
from __future__ import annotations

from pathlib import Path
from PySide6.QtCore import QBuffer, QIODevice, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)
from ..services.ai_service import AIService
from ..services.export_service import export_all
from ..services.settings_service import SettingsService, validate_ai
from .palette import P
from .widgets import design as _design
from .widgets.ai_connection import ConnectionTest
from .widgets.ai_thinking_controls import AIThinkingControls
from ..core.avatars import DEFAULT_AVATAR, normalize_avatar
from .widgets.personal_settings import PersonalSettingsPanel
from .widgets.avatar import AVATAR_NOTES
from .widgets.design import (
    FONT_BODY, FONT_HELPER, FONT_LABEL, FIELD_HEIGHT, FIELD_HEIGHT_COMPACT,
    FOCUS_WIDTH, RADIUS, PaperField, PaperHeading, button_height,
)


def scale_for(width: int, height: int) -> float:
    """共享层尺度系数 `design.scale_factor`（唯一口径，不自己另造 token）。"""
    shared = getattr(_design, 'scale_factor', None)
    if callable(shared):
        try:
            return float(shared(width, height))
        except Exception:
            pass
    return max(0.85, min(1.15, min(width / 1440.0, height / 1024.0)))


def _interp(low: int, high: int, scale: float) -> int:
    """在上下限区间里按尺度系数取值（0.85 → low，1.00 → high）。"""
    t = max(0.0, min(1.0, (float(scale) - 0.85) / 0.15))
    return int(round(low + (high - low) * t))


_AI_BACKENDS = [('off', '关闭'), ('openai', 'OpenAI 兼容'), ('ollama', 'Ollama 本地')]
_AI_PLACEHOLDERS = {
    'openai': ('https://api.openai.com/v1', '输入服务提供方的 API Key'),
    'ollama': ('http://127.0.0.1:11434/v1', ''),
}
_SECTIONS = ('个人资料', '统计规则', '应用排除', 'AI配置', '外观', '数据备份')

# 侧栏底色/选中色由纸张派生，纸面正文/辅助文字在极暗主题下兜底到可读色。
# 配方（design-recipe.md §2）：设置左栏是纸面同色系浅填充 `#E0D6CC`（12/10 圆角、
# 无描边），不是「主题 surface + 1px 硬边」；这里按配方改为纸面加深一档。
_SIDEBAR_TINT = 0.10          # 纸面加深一档（等价设计稿 #E0D6CC 之于 #EEE5D6）
_INPUT_WHITEN = 0.55          # 表单输入底：纸面向白提亮（等价设计稿 #F8F2E8）
_CONTRAST_MIN = 4.5
# 侧栏宽度 / 表单间距的上下限区间（由尺度系数插值）
_SIDEBAR_W_MIN, _SIDEBAR_W_MAX = 168, 208
_FIELD_GAP_MIN, _FIELD_GAP_MAX = 12, 18
_FORM_PAD_MIN, _FORM_PAD_MAX = 14, 20


# ---------- 颜色与对比度（只用于纸面可读性兜底） ----------

def _rgb(color) -> tuple:
    c = QColor(color)
    if not c.isValid():
        c = QColor('#000000')
    return (c.red(), c.green(), c.blue())


def _hex(rgb) -> str:
    return '#%02X%02X%02X' % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def _blend(color_a, color_b, t: float) -> str:
    a, b = _rgb(color_a), _rgb(color_b)
    return _hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def _luminance(color) -> float:
    channels = []
    for value in _rgb(color):
        c = value / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(color_a, color_b) -> float:
    la, lb = _luminance(color_a), _luminance(color_b)
    lo, hi = min(la, lb), max(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _readable(fg, bg, minimum: float = _CONTRAST_MIN) -> str:
    """把前景色按需向黑/白收敛，直到与背景的对比度达标（不发明新颜色，只调明暗）。"""
    if _contrast(fg, bg) >= minimum:
        return str(fg)
    for target in ('#000000', '#FFFFFF'):
        for step in range(1, 26):
            candidate = _blend(fg, target, step * 0.04)
            if _contrast(candidate, bg) >= minimum:
                return candidate
    return '#FFFFFF' if _luminance(bg) < 0.5 else '#000000'


# ---------- 纸张容器（底部操作栏留在纸张外，滚动只发生在表单内部） ----------

class _PaperFrame(QFrame):
    """整块奶油纸张：不透明、轻微不规则边缘，与 design.PaperSurface 同一视觉语言。

    自己绘制而非复用 `PaperSurface`，是因为需要一层不透明的纸张底：
    QDialog 在深色主题下窗口底色是画布色，若纸张只作为子容器，四周会露出深色边。
    """

    @staticmethod
    def _paper_path(rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        left, right = rect.left() + 1.0, rect.right() - 1.0
        top, bottom = rect.top() + 3.0, rect.bottom() - 3.0
        width = max(1.0, right - left)
        segments = 8
        path.moveTo(left + 8, top)
        for i in range(1, segments + 1):
            x = left + width * i / segments
            control_y = top + (1.8 if i % 2 else -1.6)
            path.quadTo(left + width * (i - 0.5) / segments, control_y, x, top)
        path.lineTo(right - 8, bottom)
        for i in range(segments - 1, -1, -1):
            x = left + width * i / segments
            control_y = bottom + (-1.8 if i % 2 else 1.6)
            path.quadTo(left + width * (i + 0.5) / segments, control_y, x, bottom)
        path.closeSubpath()
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = self._paper_path(QRectF(self.rect()))
        painter.fillPath(path, QColor(P.paper))
        painter.setPen(QPen(QColor(P.paper_muted), 1))
        painter.drawPath(path)
        painter.end()


class SettingsDialog(QDialog):
    def __init__(self, repo, balance, parent=None, theme_manager=None, data_dir=None, test_session=None):
        super().__init__(parent)
        self.setWindowTitle('设置 · 星光伴学')
        from .widgets.window_policy import FixedWindowPolicy
        self._window_policy = FixedWindowPolicy(self, (820, 640))
        self.setSizeGripEnabled(False)
        self._repo, self._balance = repo, balance
        self._theme_mgr = theme_manager
        self._data_dir = Path(data_dir) if data_dir else None
        self._service = SettingsService(repo, data_dir)
        self._original_theme = theme_manager.current_id() if theme_manager else None
        self._avatar_action = None
        self._pending_deletions = set()
        self._test_job = None
        self._test_session = test_session
        self._closed = False
        self._compact = None
        self._scale = scale_for(820, 640)
        self._style_signature = None
        self._sizes_pending = False
        self._bodies = []
        self._url_error_text = ''
        # 外观分组的三个控件只在有主题管理器时创建；先显式置空，
        # 保证 theme_manager=None 的构造路径（离屏 chrome 冒烟等）也能完成尺寸同步。
        self._theme_combo = None
        self._import_btn = None
        self._delete_btn = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        self._paper = _PaperFrame(self)
        self._paper.setObjectName('settingsPaper')
        root.addWidget(self._paper)

        paper = QVBoxLayout(self._paper)
        # 底稿 settings-dialog-820 实测：纸张左边缘贴齐窗口（x=0），右侧留 24px，
        # 顶 20 / 底 14；左右不对称是设计稿的纸张构图，不是排版误差。
        paper.setContentsMargins(4, 20, 24, 14)
        paper.setSpacing(16)
        self._paper_layout = paper

        body = QHBoxLayout()
        body.setSpacing(20)
        self._body_layout = body
        # 纸张左边缘贴齐窗口（设计稿 settings-dialog-820 的 x=0），选择态药丸由左侧
        # 缩进让出空间，否则 macOS 风格的选中底色会被纸张左边缘裁掉。
        self._sections_indent = 20
        body.setContentsMargins(self._sections_indent, 0, 0, 0)
        self._sections = QListWidget(self._paper)
        self._sections.setObjectName('settingsSections')
        self._sections.setAccessibleName('设置分类')
        self._sections.setFrameShape(QFrame.NoFrame)
        self._sections.setFixedWidth(_SIDEBAR_W_MAX)
        self._sections.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._sections.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self._sections.setUniformItemSizes(True)
        self._sections.setAttribute(Qt.WA_StyledBackground, True)
        # 配方（design-recipe.md §6.3 第 279/322 行）：左栏是一块纸面同色系浅填充
        # （`#E0D6CC`，12px 圆角、无描边）。纸张上不加底板的话，选中药丸会显得悬空。
        self._style_sections()
        # QListWidget 会给 viewport 留约 6px 默认边距；纸张左边缘贴齐窗口后，
        # 这点边距正好把选中态药丸挤出纸张、看起来被裁掉，这里清零。
        self._sections.viewport().setContentsMargins(0, 0, 0, 0)
        for name in _SECTIONS:
            self._sections.addItem(name)
        self._pages = QStackedWidget(self._paper)
        self._sections.currentRowChanged.connect(self._pages.setCurrentIndex)
        body.addWidget(self._sections)
        body.addWidget(self._pages, 1)
        paper.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        self._save_error = QLabel('')
        self._save_error.setWordWrap(True)
        self._save_error.setTextFormat(Qt.PlainText)
        self._save_error.setProperty('textRole', 'paperDanger')
        self._save_error.setVisible(False)
        footer.addWidget(self._save_error)
        footer.addStretch(1)
        self._cancel_btn = QPushButton('取消', self._paper)
        self._cancel_btn.setProperty('buttonRole', 'secondary')
        self._cancel_btn.setAutoDefault(False)
        self._cancel_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton('保存设置', self._paper)
        self._save_btn.setProperty('buttonRole', 'primary')
        self._save_btn.setDefault(True)
        self._save_btn.clicked.connect(self.accept)
        footer.addWidget(self._cancel_btn)
        footer.addWidget(self._save_btn)
        paper.addLayout(footer)

        self._build_profile()
        self._build_rules()
        self._build_exclusion()
        self._build_ai()
        self._build_appearance()
        self._build_data()
        self._sections.setCurrentRow(0)

        self._ai_backend.currentIndexChanged.connect(self._ai_placeholder)
        self._ai_url.textChanged.connect(self.check_ai_url)
        self._ai_url.textChanged.connect(self._update_thinking_context)
        self._ai_model.textChanged.connect(self._update_thinking_context)

        self._apply_metrics(force=True)
        self._refresh_style()

    # ---------- 表单分组 ----------

    def _section(self, title, hint):
        """右侧一个可滚动分组页：纸张标题 + 表单，内部滚动而不是压缩字号。

        内容 widget 必须保留 Python 引用，否则布局会被垃圾回收（Qt 所有权在 Python 侧）。
        """
        scroll = QScrollArea(self._paper)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.StrongFocus)
        body = QWidget()
        self._bodies.append(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 11, 0)
        layout.setSpacing(18)
        layout.addWidget(PaperHeading(title, hint))
        scroll.setWidget(body)
        self._pages.addWidget(scroll)
        return layout

    def _build_profile(self):
        layout = self._section('我的角色小档案', '头像、昵称和签名，一起收进成长页。')
        self._avatar_preset = normalize_avatar(self._repo.get_setting('avatar_preset', DEFAULT_AVATAR))
        editor = PersonalSettingsPanel(
            self._repo.get_setting('nickname', '打字新星'),
            self._repo.get_setting('signature', '键盘上的舞者 ✨'), self._avatar_preset)
        self._profile_editor = editor
        self._nick_edit, self._sig_edit = editor.nickname_edit, editor.signature_edit
        self._avatar_combo = None
        self._upload_btn, self._clear_btn = editor.upload_button, editor.clear_button
        self._avatar_status = editor.status
        editor.upload_requested.connect(self._upload_avatar)
        editor.clear_requested.connect(self._clear_avatar)
        editor.picker.selected.connect(self._select_avatar)
        if self._data_dir and self._repo.get_setting('avatar_image', '') == '1':
            image = QImage(str(self._data_dir / 'avatars/avatar.png'))
            if not image.isNull():
                editor.portrait.set_portrait(self._avatar_preset, image)
        layout.addWidget(editor)
        layout.addStretch()

    def _build_rules(self):
        layout = self._section('统计规则', '统计数值始终按 tw 口径计算，单位名称仅改变显示。')
        self._unit_edit = QLineEdit(self._repo.get_setting('unit_name', self._balance['unit']['name']))
        self._unit_edit.setMaxLength(8)
        layout.addWidget(PaperField('显示单位', self._unit_edit, '1 字母 = 1 tw，1 汉字 = 2 tw。建议保留 tw。'))
        self._hour_spin = QSpinBox()
        self._hour_spin.setRange(0, 23)
        self._hour_spin.setSuffix(' 点')
        self._hour_spin.setValue(int(self._repo.get_setting('day_start_hour', self._balance['day_start_hour'])))
        layout.addWidget(PaperField('新一天的起点', self._hour_spin, '改变统计日的边界，不会删除已有记录。'))
        self._infinite = QCheckBox('100 级后继续累积等级')
        self._infinite.setChecked(self._repo.get_setting('infinite_levels', '0') == '1')
        layout.addWidget(self._check_row(self._infinite, '开启后等级没有上限。'))
        layout.addStretch()

    def _build_exclusion(self):
        layout = self._section('应用排除', '在这些程序里输入时暂停统计。')
        self._exclude_edit = QPlainTextEdit(self._repo.get_setting('excluded_apps', ''))
        self._exclude_edit.setMinimumHeight(180)
        self._exclude_edit.setPlaceholderText('PasswordManager.exe\n每行一个程序名')
        layout.addWidget(PaperField(
            '排除程序', self._exclude_edit, '填写可执行文件名，每行一个；保存后立即更新统计规则。'))
        layout.addStretch()

    def _build_ai(self):
        layout = self._section('AI 配置', '为训练页生成范文。测试连接只检查当前草稿，不写入设置。')
        self._ai_backend = QComboBox()
        for value, label in _AI_BACKENDS:
            self._ai_backend.addItem(label, value)
        self._ai_backend.setCurrentIndex(
            max(0, self._ai_backend.findData(self._repo.get_setting('ai_backend', 'off'))))
        layout.addWidget(PaperField('服务类型', self._ai_backend))
        self._ai_config = QWidget()
        config = QVBoxLayout(self._ai_config)
        config.setContentsMargins(0, 0, 0, 0)
        config.setSpacing(18)
        self._ai_config_layout = config
        self._ai_url = QLineEdit(self._repo.get_setting('ai_base_url', ''))
        self._ai_url_error = QLabel('')
        self._ai_url_error.setProperty('textRole', 'paperDanger')
        self._ai_url_error.setWordWrap(True)
        self._ai_url_error.setVisible(False)
        config.addWidget(self._field_with_error(
            PaperField('服务地址 · Base URL', self._ai_url, '留空使用默认地址。'),
            self._ai_url_error))
        self._ai_key = QLineEdit(self._repo.get_setting('ai_api_key', ''))
        self._ai_key.setEchoMode(QLineEdit.Password)
        self._key_field = PaperField('API Key', self._ai_key, '保存在本机。')
        config.addWidget(self._key_field)
        self._ai_model = QLineEdit(self._repo.get_setting('ai_model', ''))
        config.addWidget(PaperField('模型名称', self._ai_model, '留空使用默认模型。'))
        self._ai_thinking_controls = AIThinkingControls(
            self._repo.get_setting('ai_thinking', '0'),
            self._repo.get_setting('ai_thinking_protocol', 'auto'), self._test_session)
        self._ai_thinking_controls.test_mode_changed.connect(self._ai_test_mode_changed)
        config.addWidget(self._ai_thinking_controls)
        layout.addWidget(self._ai_config)
        self._test_btn = QPushButton('测试连接')
        self._test_btn.setProperty('buttonRole', 'secondary')
        self._test_btn.setAutoDefault(False)
        self._test_btn.clicked.connect(self._ai_test)
        layout.addWidget(self._test_btn, 0, Qt.AlignLeft)
        self._ai_result = QLabel('')
        self._ai_result.setWordWrap(True)
        self._ai_result.setTextFormat(Qt.PlainText)
        self._ai_result.setProperty('textRole', 'paperMuted')
        layout.addWidget(self._ai_result)
        layout.addStretch()

    def _build_appearance(self):
        layout = self._section('外观', '萨莉安娜是这款软件的拟人化形象，界面统一使用她的夜色舞台风格。')
        if self._theme_mgr:
            self._theme_combo = QComboBox()
            layout.addWidget(PaperField(
                '界面外观', self._theme_combo, '当前外观：萨莉安娜。'))
            self._theme_combo.setEnabled(False)
            self._import_btn = QPushButton('导入主题包')
            self._import_btn.setProperty('buttonRole', 'secondary')
            self._import_btn.setAutoDefault(False)
            self._import_btn.clicked.connect(self._import_theme)
            self._delete_btn = QPushButton('删除用户主题')
            self._delete_btn.setProperty('buttonRole', 'secondary')
            self._delete_btn.setAutoDefault(False)
            self._delete_btn.clicked.connect(self._delete_theme)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(12)
            row_layout.addWidget(self._import_btn)
            row_layout.addWidget(self._delete_btn)
            row_layout.addStretch()
            layout.addWidget(row)
            row.hide()
            self._theme_note = QLabel('少女、星光与纸张共同构成固定外观。')
            self._theme_note.setProperty('textRole', 'paperMuted')
            self._theme_note.setWordWrap(True)
            layout.addWidget(self._theme_note)
            self._reload_themes()
            self._theme_combo.currentIndexChanged.connect(self._apply_theme)
        else:
            self._theme_combo = None
            self._delete_btn = None
            note = QLabel('当前运行环境未提供主题管理器。')
            note.setProperty('textRole', 'paperMuted')
            note.setWordWrap(True)
            layout.addWidget(note)
        self._motion = QCheckBox('动态效果')
        self._motion.setChecked(self._repo.get_setting('reduced_motion', '0') != '1')
        layout.addWidget(self._check_row(self._motion, 'Sariana 眨眼与手绘发丝、星空、导航和作答小星光；关闭后保持静态。'))
        from .companion.settings import CompanionSettings
        self._companion_settings = CompanionSettings(self._repo)
        self._companion_settings.workshop_requested.connect(self._open_companion_workshop)
        self._companion_settings.workshop_button.setEnabled(bool(getattr(self.parent(), '_companion', None)))
        layout.addWidget(self._companion_settings)
        layout.addStretch()

    def _open_companion_workshop(self):
        controller = getattr(self.parent(), '_companion', None)
        if controller is not None:
            self.accept()
            if self.result() == QDialog.Accepted:
                QTimer.singleShot(0, controller.open_workshop)

    def _build_data(self):
        layout = self._section('数据备份', '导出当前记录，方便迁移或自己留存。')
        self._export_btn = QPushButton('导出数据备份')
        self._export_btn.setProperty('buttonRole', 'secondary')
        self._export_btn.setAutoDefault(False)
        self._export_btn.clicked.connect(self._export)
        layout.addWidget(self._export_btn, 0, Qt.AlignLeft)
        note = QLabel('包含 daily_stats.csv 与 data.json；二创作品请在本地二创工坊单独导出。')
        note.setWordWrap(True)
        note.setProperty('textRole', 'paperMuted')
        layout.addWidget(note)
        self._data_dir_note = QLabel(f'当前数据目录：{self._data_dir}' if self._data_dir else '当前数据目录未知。')
        self._data_dir_note.setWordWrap(True)
        self._data_dir_note.setProperty('textRole', 'paperMuted')
        layout.addWidget(self._data_dir_note)
        layout.addStretch()

    def _check_row(self, checkbox, hint):
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(checkbox)
        helper = QLabel(hint)
        helper.setWordWrap(True)
        helper.setProperty('textRole', 'paperMuted')
        layout.addWidget(helper)
        return row

    def _field_with_error(self, field, error_label):
        """字段 + 就近错误提示：错误紧跟控件左侧，不另起一列。"""
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(field)
        layout.addWidget(error_label)
        return box

    # ---------- 尺寸与外观 ----------

    def _apply_metrics(self, *, force=False):
        """按可用空间升降级内边距与控件高度（字号不缩）。

        Qt 会在 show/polish 之后重算尺寸约束（`setFixedHeight` 的最小值会被 QSS 覆盖），
        所以本方法是幂等的：任何时点重复调用都得到同一套尺寸，`showEvent` 里再补一次。

        尺寸档阈值与主窗口的 `is_compact` 不同：底稿 `settings-dialog-820.png` 在
        820×640 下用的是**常规**控件高度（字段 44、按钮 44、侧栏 52 行高），
        规格里 820×640 是「实际尺寸稿」、700×540 才是最低尺寸档；
        主窗口的 640 高阈值会把 820×640 判成紧凑，字段缩到 40、侧栏 40，
        与底稿实测对不上。

        判据取纸张自己的尺寸而不是 `self.width()/height()`：`_PaperFrame` 是对话框的
        直接子控件，铺满内容区，尺寸随窗口确定；而 `self.width()` 在构造/首次 polish
        期间可能还是布局默认值，会把 820×640 误判成紧凑档（实测字段停 40、底栏顶出纸张）。
        """
        compact = self._paper.width() <= 740 or self._paper.height() <= 560
        # 尺度系数取纸张自身尺寸：820×640 是设计实际尺寸稿 → 1.00 附近，
        # 700×540 最低档 → 下限。所有间距/宽度都从它插值，不再只有两档跳变。
        scale = scale_for(max(1, self._paper.width()), max(1, self._paper.height()))
        if not force and compact == self._compact and abs(scale - self._scale) < 0.005:
            return
        self._scale = scale
        self._compact = compact
        paper = self._paper_layout
        # 左 4px：让侧栏选中态药丸完整落在纸张内。
        # 上 20：底稿上边距就是 20（侧栏/表单都从 y=60 起，扣掉 42 的窗口标题栏）。
        # 常规档若沿用 paper_padding(False)=32，820×640 下「上 32 + 内容 550 + 底栏 52」
        # 会顶出纸张 8px（layout_audit 报越界），所以这里按底稿取 20。
        paper.setContentsMargins(4, 20, 24 if not compact else 20, 14)
        paper.setSpacing(12 if compact else 16)
        self._body_layout.setSpacing(14 if compact else 20)
        self._body_layout.setContentsMargins(self._sections_indent, 0, 0, 0)
        self._sections.setFixedWidth(_interp(_SIDEBAR_W_MIN, _SIDEBAR_W_MAX, self._scale))
        if self._sections.count():
            row_height = 44 if compact else 52
            self._sections.setGridSize(QSize(self._sections.width(), row_height))
            for index in range(self._sections.count()):
                self._sections.item(index).setSizeHint(QSize(self._sections.width(), row_height))
        for layout in self._field_layouts():
            layout.setSpacing(_interp(_FIELD_GAP_MIN, _FIELD_GAP_MAX, self._scale))
        self._sections.viewport().setContentsMargins(
            0, 0, 0, 0)
        self._style_sections()
        self._sync_field_heights()

    def _pin_min_height(self, control, min_height: int) -> None:
        """给控件钉一条**控件级** min-height（比 app 级 QSS 的 `min-height: 26px` 优先）。

        只写与控件类型匹配的选择器，让主题里带后代选择器的规则（表单底色/描边/圆角、
        `buttonRole` 等）仍然生效——用整段样式覆盖会把主题色一起抹掉。
        """
        if control is None:
            return
        if isinstance(control, QPlainTextEdit):
            selector = 'QPlainTextEdit'
        elif isinstance(control, QPushButton):
            selector = 'QPushButton'
        elif isinstance(control, (QComboBox, QSpinBox)):
            selector = 'QComboBox, QSpinBox'
        elif isinstance(control, QLineEdit):
            selector = 'QLineEdit'
        else:
            selector = 'QWidget'
        control.setStyleSheet(f'{selector} {{ min-height: {int(min_height)}px; }}')

    def _sync_field_heights(self):
        """控件高度按当前尺寸档位设置（正文/辅助字号由 QSS 决定，不在这里改）。

        同时钉一条控件级 `min-height`：主题 QSS 的 `QLineEdit/QComboBox/QSpinBox
        { min-height: 26px }` 与 `QPushButton { min-height: 26px }` 会在 polish 时
        盖掉控件级固定高度，只设高度会在主题应用后失效。
        """
        height = FIELD_HEIGHT_COMPACT if self._compact else FIELD_HEIGHT
        for control in (self._nick_edit, self._sig_edit, self._unit_edit, self._hour_spin,
                        self._avatar_combo, self._ai_backend, self._ai_url, self._ai_key,
                        self._ai_model, self._ai_thinking_controls.protocol, self._theme_combo):
            if control is not None:
                self._pin_min_height(control, height - 20)
                control.setFixedHeight(height)
        exclude_h = 140 if self._compact else _interp(140, 180, self._scale)
        self._pin_min_height(self._exclude_edit, exclude_h - 24)
        self._exclude_edit.setMinimumHeight(exclude_h)
        small = button_height(self._compact)
        for control in (self._save_btn, self._cancel_btn, self._upload_btn, self._clear_btn,
                        self._test_btn, self._export_btn, self._import_btn, self._delete_btn):
            if control is not None:
                self._pin_min_height(control, small)
                control.setFixedHeight(small)

    def _field_layouts(self):
        layouts = [self._ai_config_layout]
        for index in range(self._pages.count()):
            page = self._pages.widget(index)
            body = page.widget() if isinstance(page, QScrollArea) else None
            if body is not None and body.layout() is not None:
                layouts.append(body.layout())
        return layouts

    def _reapply_sizes(self):
        self._apply_metrics(force=True)
        self._sync_field_heights()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_metrics()
        self._check_style_freshness()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_metrics()
        self._check_style_freshness()
        if not self._sizes_pending:
            # Qt 在首次 polish/show 之后会重算 QSS 尺寸约束，压制 setFixedHeight 的最小高度。
            self._sizes_pending = True
            QTimer.singleShot(0, self._reapply_sizes)

    def _check_style_freshness(self):
        """取消主题预览后，本对话框自带的 QSS 也要跟着调色板回到原主题。"""
        if self._style_signature is not None and self._style_signature != self._palette_signature():
            self._refresh_style()

    def _palette_signature(self):
        return (P.paper, P.paper_text, P.paper_muted, P.canvas, P.primary,
                P.primary_text, P.border, P.focus, self._focus_color(), P.surface_text)

    def _focus_color(self):
        """纸张上的焦点轮廓：优先用公共调色板的 focus_on_paper（奶油纸上可见），
        主题未提供时按纸张正文方向混深到 ≥4.5:1。"""
        token = getattr(P, 'focus_on_paper', None)
        if token:
            return token
        return _blend(P.focus, self._readable(P.paper_text, P.paper), 0.32)

    # ---------- 样式（纸张上的语义角色；颜色与尺寸取自 P / design） ----------

    def _style_sections(self):
        item = _readable(self._palette_item(), self._sidebar_bg())
        focus = self._focus_color()
        # 配方（design-recipe.md §2/§6.3）：左栏是同色系浅填充 + 12/10 圆角、**无描边**；
        # 选中项是主题主色药丸，同样不带深灰硬边（旧实现有 1px border）。
        self._sections.setStyleSheet(
            f'QListWidget#settingsSections {{ background: {self._sidebar_bg()};'
            f' border: none; border-radius: 12px;'
            f' color: {item}; font-size: {FONT_BODY}px; outline: none; padding: 0px; }}'
            f'QListWidget#settingsSections::item {{ padding: 0px 12px; margin: 0px 0px 8px 0px;'
            f' border-radius: 10px; border: none; }}'
            f'QListWidget#settingsSections::item:selected {{ background: {P.primary};'
            f' color: {P.primary_text}; font-weight: 600; }}'
            f'QListWidget#settingsSections::item:hover {{ background: {_blend(P.primary, self._sidebar_bg(), 0.72)}; }}'
            f'QListWidget#settingsSections::item:focus {{ border: {FOCUS_WIDTH}px solid {focus}; }}')

    def _refresh_style(self):
        self._ai_thinking_controls.apply_theme()
        paper_text = _readable(P.paper_text, P.paper)
        paper_muted = _readable(P.paper_muted, P.paper)
        # 配方（design-recipe.md §2 第 107 行 / §6.3 第 288、333 行）：设置表单输入是
        # 「纸面提亮一档」的 `#F8F2E8` + `#9C929F` 细描边 + 8px 圆角，不是纯白输入框、
        # 也不是深灰硬边。这里按配方派生：底色 = 纸面向白提亮，描边 = 辅助色淡化。
        input_bg = _blend('#FFFFFF', P.paper, 1.0 - _INPUT_WHITEN)
        input_border = _blend(paper_muted, P.paper, 0.42)
        input_text = _readable(paper_text, input_bg)
        # 纸面禁用态与公共组件同一口径：主色 30% 铺在纸上 + 纸张正文色（≥4.5:1）。
        disabled_bg = _blend(P.primary, P.paper, 0.70)
        placeholder = _blend(paper_muted, input_bg, 0.28)
        focus = self._focus_color()
        field_height = FIELD_HEIGHT_COMPACT if self._compact else FIELD_HEIGHT
        field_radius = _interp(10, 14, self._scale)
        # UI_SPEC：紧凑窗口只降内边距与控件高度（32→20 / 44→40 / 52→44），
        # 正文、字段标签、辅助文字的字号在任何尺寸下都不缩。
        self._paper.setStyleSheet(f'''
QFrame#settingsPaper {{ background: transparent; }}
QFrame#settingsPaper QLabel {{ color: {paper_text}; font-size: {FONT_BODY}px; }}
QFrame#settingsPaper QLabel[textRole="paperTitle"] {{ color: {paper_text}; font-size: 28px; font-weight: 600; }}
QFrame#settingsPaper QLabel[textRole="paperField"] {{ color: {paper_text}; font-size: {FONT_LABEL}px; font-weight: 600; }}
QFrame#settingsPaper QLabel[textRole="paperMuted"] {{ color: {paper_muted}; font-size: {FONT_HELPER}px; }}
QFrame#settingsPaper QLabel[textRole="paperSuccess"] {{ color: {P.success_on_paper}; font-size: {FONT_HELPER}px; }}
QFrame#settingsPaper QLabel[textRole="paperDanger"] {{ color: {P.danger_on_paper}; font-size: {FONT_HELPER}px; }}
QFrame#settingsPaper QScrollArea, QFrame#settingsPaper QScrollArea > QWidget,
QFrame#settingsPaper QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QFrame#settingsPaper QLineEdit, QFrame#settingsPaper QComboBox, QFrame#settingsPaper QSpinBox {{
    background: {input_bg}; color: {input_text}; border: 1px solid {input_border};
    border-radius: {field_radius}px; padding: 8px 12px; font-size: {FONT_BODY}px;
    min-height: {field_height - 20}px; }}
QFrame#settingsPaper QPlainTextEdit {{
    background: {input_bg}; color: {input_text}; border: 1px solid {input_border};
    border-radius: {field_radius}px; padding: 10px 12px; font-size: {FONT_BODY}px;
    selection-background-color: {P.primary}; selection-color: {P.primary_text}; }}
QFrame#settingsPaper QLineEdit:disabled, QFrame#settingsPaper QComboBox:disabled,
QFrame#settingsPaper QSpinBox:disabled {{ background: {disabled_bg}; color: {paper_muted}; }}
QFrame#settingsPaper QLineEdit:focus, QFrame#settingsPaper QComboBox:focus,
QFrame#settingsPaper QSpinBox:focus, QFrame#settingsPaper QPlainTextEdit:focus {{
    border: {FOCUS_WIDTH}px solid {focus}; }}
QFrame#settingsPaper QLineEdit::placeholder, QFrame#settingsPaper QPlainTextEdit::placeholder,
QFrame#settingsPaper QSpinBox::placeholder {{ color: {placeholder}; }}
QFrame#settingsPaper QComboBox::drop-down {{ border: none; width: 26px; }}
QFrame#settingsPaper QComboBox QAbstractItemView {{
    background: {P.paper}; color: {paper_text}; border: 1px solid {P.border};
    selection-background-color: {P.primary}; selection-color: {P.primary_text}; }}
QFrame#settingsPaper QCheckBox {{ color: {paper_text}; font-size: {FONT_BODY}px; spacing: 8px; }}
QFrame#settingsPaper QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {P.border}; background: {input_bg}; }}
QFrame#settingsPaper QCheckBox::indicator:checked {{ background: {P.primary}; border-color: {P.primary}; }}
QFrame#settingsPaper QCheckBox::indicator:focus {{ border: {FOCUS_WIDTH}px solid {focus}; }}
QFrame#settingsPaper QPushButton {{ border-radius: 10px; padding: 0 16px; font-size: {FONT_BODY}px; }}
QFrame#settingsPaper QPushButton[buttonRole="primary"] {{
    background: {P.primary}; color: {P.primary_text}; border: 1px solid {P.primary};
    font-weight: 600; padding: 0 22px; }}
QFrame#settingsPaper QPushButton[buttonRole="primary"]:hover {{
    background: {_blend(P.primary, P.paper_text, 0.12)}; }}
QFrame#settingsPaper QPushButton[buttonRole="primary"]:pressed {{
    background: {_blend(P.primary, P.paper_text, 0.22)}; }}
QFrame#settingsPaper QPushButton[buttonRole="primary"]:disabled {{
    background: {disabled_bg}; color: {paper_text}; border: 1px solid {disabled_bg}; }}
QFrame#settingsPaper QPushButton[buttonRole="primary"]:focus {{
    border: {FOCUS_WIDTH}px solid {focus}; }}
QFrame#settingsPaper QPushButton[buttonRole="secondary"] {{
    background: {_blend(paper_muted, P.paper, 0.82)}; color: {paper_text};
    border: 1px solid {P.border}; }}
QFrame#settingsPaper QPushButton[buttonRole="secondary"]:hover {{
    background: {_blend(paper_muted, P.paper, 0.68)}; }}
QFrame#settingsPaper QPushButton[buttonRole="secondary"]:disabled {{
    background: {disabled_bg}; color: {paper_text}; border: 1px solid {disabled_bg}; }}
QFrame#settingsPaper QPushButton[buttonRole="secondary"]:focus {{
    border: {FOCUS_WIDTH}px solid {focus}; }}
''')
        self._style_sections()
        self._style_signature = self._palette_signature()
        self._paper.update()

    def _sidebar_bg(self):
        """左栏底色：纸面加深一档（配方 `#E0D6CC` 的同一手法），不是深色 surface。"""
        return _blend(P.paper_text, P.paper, 1.0 - _SIDEBAR_TINT)

    def _palette_item(self):
        """侧栏条目正文：优先用主题的文字角色，对比不足时按明暗收敛。"""
        item = P.surface_text if _contrast(P.surface_text, self._sidebar_bg()) >= \
            _contrast(P.paper_text, self._sidebar_bg()) else P.paper_text
        return _readable(item, self._sidebar_bg())

    # ---------- 头像草稿 ----------

    def _upload_avatar(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择头像图片', '', '图片 (*.png *.jpg *.jpeg *.bmp *.webp)')
        if not path:
            return
        image = QImage(path)
        if image.isNull():
            self._avatar_status.setText('无法读取这张图片，请重新选择。')
            return
        image = image.scaled(512, 512, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, 'PNG')
        self._avatar_action = bytes(buffer.data())
        self._profile_editor.portrait.set_portrait(self._avatar_preset, image)
        self._avatar_status.setText('已选择新头像，保存设置后生效。')

    def _select_avatar(self, preset):
        self._avatar_preset = normalize_avatar(preset)
        self._avatar_action = False
        self._profile_editor.portrait.set_portrait(self._avatar_preset)
        self._avatar_status.setText(f'{AVATAR_NOTES[self._avatar_preset]} 保存后生效。')

    def _clear_avatar(self):
        self._profile_editor.picker.set_preset(DEFAULT_AVATAR)
        self._select_avatar(DEFAULT_AVATAR)
        self._avatar_status.setText('保存后恢复 Sariana 默认头像；取消保留原头像。')

    # ---------- AI 草稿 ----------

    def _ai_config_values(self):
        return dict(backend=self._ai_backend.currentData(), base_url=self._ai_url.text().strip(),
                    api_key=self._ai_key.text().strip(), model=self._ai_model.text().strip(),
                    **self._ai_thinking_controls.values())

    def _update_thinking_context(self, *_):
        self._ai_thinking_controls.set_context(self._ai_config_values())

    def _ai_test_mode_changed(self, enabled):
        self._ai_feedback(True, '开发者彩蛋已开启：本次运行提前解锁 AI 测试，仍消耗 API token。'
                          if enabled else '开发者彩蛋已关闭：恢复等级与训练券规则。')
        QTimer.singleShot(0, self._reveal_ai_result)

    def _ai_placeholder(self):
        self._update_thinking_context()
        backend = self._ai_backend.currentData()
        url, key = _AI_PLACEHOLDERS.get(backend, ('', ''))
        self._ai_url.setPlaceholderText(url)
        self._ai_key.setPlaceholderText(key)
        self._ai_config.setVisible(backend != 'off')
        self._key_field.setVisible(backend == 'openai')
        self._test_btn.setEnabled(backend != 'off' and self._test_job is None)
        self._ai_url_error.setVisible(False)
        self._url_error_text = ''
        # 换后端后若草稿地址仍无效，保持就近提示（空地址按规格视为「用默认地址」）。
        if backend != 'off' and self._ai_url.text().strip():
            self.check_ai_url()
        self._sync_field_heights()

    def check_ai_url(self):
        """无效地址就近提示：只检查草稿，不写数据库、不发网络请求。

        不用防抖定时器：草稿校验是纯字符串判断，立即反馈对键盘输入和离屏脚本都更确定。
        """
        error = validate_ai(self._ai_config_values())
        previous = self._url_error_text
        self._url_error_text = error
        self._ai_url_error.setText(error)
        self._ai_url_error.setVisible(bool(error))
        if error:
            self._set_result(False, error)
        elif previous:
            # 草稿改回有效地址：清掉这条错误，不覆盖连接测试结果以外的内容。
            self._set_result(True, '服务地址有效，可以测试连接。')
        return error

    def _ai_test(self):
        if self._test_job is not None:
            return
        config = self._ai_config_values()
        error = validate_ai(config)
        if error:
            self.check_ai_url()
            self._ai_feedback(False, error)
            self._ai_url.setFocus()
            return
        self._tested_config = config
        self._test_btn.setEnabled(False)
        self._ai_feedback(True, '正在测试连接…可以继续编辑或取消。')
        job = ConnectionTest(AIService(config=config), QApplication.instance())
        self._test_job = job
        job.done.connect(self._ai_test_done)
        job.done.connect(job.deleteLater)
        job.start()

    def _ai_test_done(self, ok, message):
        self._test_job = None
        if self._closed:
            return
        self._ai_placeholder()
        if self._ai_config_values() != self._tested_config:
            self._ai_feedback(False, '配置已修改，请重新测试当前草稿。')
        else:
            self._ai_feedback(ok, message)
        QTimer.singleShot(0, self._reveal_ai_result)

    def _reveal_ai_result(self):
        if not self._closed and self._pages.currentIndex() == 3:
            self._pages.currentWidget().ensureWidgetVisible(self._ai_result, 0, 12)

    def _set_result(self, ok, message):
        self._ai_result.setText(message)
        self._ai_result.setProperty('textRole', 'paperSuccess' if ok else 'paperDanger')
        self._ai_result.style().unpolish(self._ai_result)
        self._ai_result.style().polish(self._ai_result)

    def _ai_feedback(self, ok, message):
        self._set_result(ok, message)

    # ---------- 主题草稿 ----------

    def _reload_themes(self):
        selected = self._theme_combo.currentData() or self._original_theme
        self._theme_combo.blockSignals(True)
        self._theme_combo.clear()
        for theme in self._theme_mgr.list_themes():
            if theme['id'] not in self._pending_deletions:
                self._theme_combo.addItem(theme['name'], theme['id'])
        self._theme_combo.setCurrentIndex(max(0, self._theme_combo.findData(selected)))
        self._theme_combo.blockSignals(False)
        self._update_delete_button()

    def _update_delete_button(self):
        if self._delete_btn is None:
            return
        theme = self._theme_mgr.get(self._theme_combo.currentData())
        self._delete_btn.setEnabled(bool(theme and not theme['_builtin']))

    def _apply_theme(self, *_):
        theme = self._theme_combo.currentData()
        if theme:
            self._theme_mgr.apply(theme, persist=False)
            self._refresh_style()
            self._update_delete_button()

    def _import_theme(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择主题包', '', '主题包 (*.zip)')
        if not path:
            return
        ok, message = self._theme_mgr.import_theme(path)
        QMessageBox.information(self, '导入主题', message)
        if ok:
            self._reload_themes()

    def _delete_theme(self):
        theme = self._theme_mgr.get(self._theme_combo.currentData())
        if not theme or theme['_builtin']:
            return
        if QMessageBox.question(self, '删除用户主题', '保存设置时删除该主题包，是否继续？') != QMessageBox.Yes:
            return
        self._pending_deletions.add(theme['id'])
        self._reload_themes()
        self._apply_theme()

    def _export(self):
        output = QFileDialog.getExistingDirectory(self, '选择导出目录')
        if not output:
            return
        try:
            folder = export_all(self._repo, output)
            QMessageBox.information(self, '导出完成', f'备份已保存到：\n{folder}')
        except OSError as error:
            QMessageBox.warning(self, '导出失败', str(error))

    # ---------- 提交与取消 ----------

    def accept(self):
        config = self._ai_config_values()
        error = validate_ai(config)
        if error:
            self._sections.setCurrentRow(3)
            self.check_ai_url()
            self._ai_feedback(False, error)
            self._ai_url.setFocus()
            return
        values = dict(nickname=self._nick_edit.text().strip() or '打字新星',
                      signature=self._sig_edit.text().strip() or '键盘上的舞者 ✨',
                      avatar_preset=self._avatar_preset,
                      unit_name=self._unit_edit.text().strip() or 'tw',
                      day_start_hour=str(self._hour_spin.value()),
                      infinite_levels='1' if self._infinite.isChecked() else '0',
                      excluded_apps=self._exclude_edit.toPlainText(),
                      reduced_motion='0' if self._motion.isChecked() else '1')
        values.update({f'ai_{key}': value for key, value in config.items()})
        values.update(self._companion_settings.values())
        if self._theme_mgr:
            values['theme_id'] = self._theme_combo.currentData()
        try:
            self._service.save(values, self._avatar_action)
        except Exception:
            self._save_error.setText('设置未保存，请检查数据目录是否可写后重试。草稿仍保留。')
            self._save_error.setVisible(True)
            return
        if self._theme_mgr:
            for theme_id in self._pending_deletions:
                self._theme_mgr.delete_theme(theme_id)
            self._theme_mgr.apply(values['theme_id'], persist=False)
        self._closed = True
        super().accept()

    def reject(self):
        self._closed = True
        if self._theme_mgr:
            self._theme_mgr.apply(self._original_theme, persist=False)
        self._refresh_style()
        super().reject()
