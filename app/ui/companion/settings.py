"""Draft-only companion controls composed into the existing appearance form."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLabel, QCheckBox, QComboBox, QSpinBox, QPushButton


class CompanionSettings(QWidget):
    workshop_requested = Signal()

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(10)
        title = QLabel('Sariana 小伙伴')
        title.setProperty('textRole', 'paperText')
        title.setStyleSheet('font-weight:600;font-size:17px;background:transparent;')
        layout.addWidget(title)
        self.enabled = QCheckBox('开启角色陪伴')
        self.enabled.setChecked(repo.get_setting('companion_enabled', '1') != '0')
        layout.addWidget(self.enabled)
        form = QFormLayout()
        self.mode = QComboBox()
        for title, value in [('应用窗口内', 'window'), ('桌面宠物', 'desktop')]:
            self.mode.addItem(title, value)
        self.mode.setCurrentIndex(max(0, self.mode.findData(repo.get_setting('companion_mode', 'window'))))
        form.addRow('显示方式', self.mode)
        self.frequency = QComboBox()
        for title, value in [('安静 · 每 8–12 分钟', 'quiet'), ('适中 · 每 4–7 分钟', 'normal'),
                             ('活泼 · 每 2–4 分钟', 'lively'), ('暂停主动互动', 'off')]:
            self.frequency.addItem(title, value)
        self.frequency.setCurrentIndex(max(0, self.frequency.findData(repo.get_setting('companion_frequency', 'normal'))))
        form.addRow('偶发互动频率', self.frequency)
        self.size = QSpinBox()
        self.size.setRange(100, 220)
        self.size.setSuffix(' 像素')
        try:
            self.size.setValue(int(repo.get_setting('companion_size', '160')))
        except ValueError:
            self.size.setValue(160)
        form.addRow('角色大小', self.size)
        layout.addLayout(form)
        self.bubbles = QCheckBox('显示角色话术气泡')
        self.bubbles.setChecked(repo.get_setting('companion_bubbles', '1') != '0')
        layout.addWidget(self.bubbles)
        note = QLabel('拖动角色可自由摆放，拖出应用窗口即可放到桌面；桌面位置会记住，主窗口收起后继续陪伴。练习时暂停动效，上方开关可统一关闭。')
        note.setWordWrap(True)
        note.setProperty('textRole', 'paperMuted')
        layout.addWidget(note)
        self.workshop_button = QPushButton('保存设置并打开二创工坊')
        self.workshop_button.setProperty('buttonRole', 'secondary')
        self.workshop_button.setAutoDefault(False)
        self.workshop_button.clicked.connect(self.workshop_requested)
        layout.addWidget(self.workshop_button)

    def values(self):
        return {
            'companion_enabled': '1' if self.enabled.isChecked() else '0',
            'companion_mode': self.mode.currentData(),
            'companion_frequency': self.frequency.currentData(),
            'companion_size': str(self.size.value()),
            'companion_bubbles': '1' if self.bubbles.isChecked() else '0',
        }
