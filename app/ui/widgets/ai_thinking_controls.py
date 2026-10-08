"""AI 思考草稿、兼容协议提示与会话彩蛋；不读写数据库。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from ...services.ai_protocol import PROTOCOLS, THINKING_LIMIT, thinking_policy
from ...services.ai_service import AIService
from ..palette import P
from .design import PaperField


class AIThinkingControls(QWidget):
    test_mode_changed = Signal(bool)

    def __init__(self, thinking='0', protocol='auto', test_session=None, parent=None):
        super().__init__(parent)
        self._context = {}
        self._test_session = test_session
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        row = QHBoxLayout()
        self.toggle = QCheckBox('思考模式')
        self.toggle.setChecked(thinking == '1')
        self.toggle.setAccessibleName('思考模式')
        self.toggle.setMinimumHeight(44)
        row.addWidget(self.toggle)
        row.addStretch()
        self.egg_button = QPushButton('✧')
        self.egg_button.setCheckable(True)
        self.egg_button.setAutoDefault(False)
        self.egg_button.setFixedSize(32, 32)
        self.egg_button.setCursor(Qt.PointingHandCursor)
        self.egg_button.setToolTip('一点星光')
        self.egg_button.setAccessibleName('开发者彩蛋')
        self.egg_button.setEnabled(test_session is not None)
        self.egg_button.setChecked(bool(test_session and test_session.enabled))
        self.egg_button.toggled.connect(self._egg_toggled)
        row.addWidget(self.egg_button)
        layout.addLayout(row)
        self.warning = QLabel(
            '高消耗提醒：开启思考可能消耗极高的 token，并增加费用与等待时间。'
            f'输出预算提高至 {THINKING_LIMIT:,} token；思考计入或单独限额依接口而定，短文本练习建议关闭。')
        self.warning.setWordWrap(True)
        self.warning.setTextFormat(Qt.PlainText)
        self.warning.setProperty('textRole', 'paperDanger')
        layout.addWidget(self.warning)
        self.protocol = QComboBox()
        self.protocol.setAccessibleName('思考开关协议')
        for value, label in PROTOCOLS:
            self.protocol.addItem(label, value)
        self.protocol.setCurrentIndex(max(0, self.protocol.findData(protocol)))
        layout.addWidget(PaperField('思考开关协议', self.protocol, '默认自动识别；自定义代理可手动选择。'))
        self.capability = QLabel()
        self.capability.setWordWrap(True)
        self.capability.setTextFormat(Qt.PlainText)
        self.capability.setProperty('textRole', 'paperMuted')
        layout.addWidget(self.capability)
        self.protocol.currentIndexChanged.connect(self._refresh)
        self.toggle.toggled.connect(self._refresh)
        self.apply_theme()

    def values(self):
        return {'thinking': '1' if self.toggle.isChecked() else '0',
                'thinking_protocol': self.protocol.currentData()}

    def set_context(self, config):
        self._context = {key: config.get(key, '') for key in ('backend', 'base_url', 'model')}
        self._refresh()

    def _refresh(self, *_):
        config = dict(self._context, **self.values())
        try:
            service = AIService(config=config)
            policy = thinking_policy(config, service._endpoint(), service._model())
            self.capability.setText(policy.description)
        except (KeyError, ValueError):
            self.capability.setText('填好服务地址与模型名称后，将自动识别思考协议。')

    def _egg_toggled(self, enabled):
        if self._test_session is not None:
            self._test_session.enabled = enabled
            self.test_mode_changed.emit(enabled)

    def apply_theme(self):
        self.egg_button.setStyleSheet(
            f'QPushButton {{background:transparent;color:{P.paper_muted};border:none;'
            'min-width:28px;max-width:28px;min-height:28px;max-height:28px;padding:0;font-size:18px;}'
            f'QPushButton:checked {{color:{P.danger_on_paper};}}'
            f'QPushButton:focus {{border:1px solid {P.focus_on_paper};border-radius:8px;}}')
