"""个人资料草稿视图：身份便签、偏移肖像和五款头像。"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget
from .avatar import AvatarPicker, PortraitCard
from .design import PaperField
from .scrapbook import ScrapbookCard


class PersonalSettingsPanel(QWidget):
    upload_requested = Signal()
    clear_requested = Signal()

    def __init__(self, nickname, signature, preset, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        hero = QHBoxLayout()
        hero.setSpacing(9)
        note = ScrapbookCard('rose')
        fields = QVBoxLayout(note)
        fields.setContentsMargins(20, 20, 27, 23)
        fields.setSpacing(10)
        self.nickname_edit = QLineEdit(nickname)
        self.nickname_edit.setMaxLength(12)
        self.signature_edit = QLineEdit(signature)
        self.signature_edit.setMaxLength(30)
        fields.addWidget(PaperField('给自己一个名字', self.nickname_edit))
        fields.addWidget(PaperField('今日人设签名', self.signature_edit))
        helper = QLabel('昵称最多 12 字 · 签名最多 30 字')
        helper.setProperty('textRole', 'paperMuted')
        helper.setWordWrap(True)
        fields.addWidget(helper)
        hero.addWidget(note, 1)
        self.portrait = PortraitCard()
        self.portrait.set_portrait(preset)
        hero.addWidget(self.portrait, 0, Qt.AlignTop)
        layout.addLayout(hero)
        label = QLabel('Sariana 的五种小心情')
        label.setProperty('textRole', 'paperField')
        layout.addWidget(label)
        self.picker = AvatarPicker(preset)
        layout.addWidget(self.picker)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.upload_button = QPushButton('用自己的照片')
        self.clear_button = QPushButton('恢复 Sariana 默认')
        for button in (self.upload_button, self.clear_button):
            button.setProperty('buttonRole', 'secondary')
            button.setAutoDefault(False)
            actions.addWidget(button, 1)
        self.upload_button.clicked.connect(self.upload_requested)
        self.clear_button.clicked.connect(self.clear_requested)
        layout.addLayout(actions)
        self.status = QLabel('选一张陪你敲键盘的脸，保存后生效。')
        self.status.setWordWrap(True)
        self.status.setProperty('textRole', 'paperMuted')
        layout.addWidget(self.status)
