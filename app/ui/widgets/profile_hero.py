"""个人中心主视觉：头像、昵称与身份标签。展示真实资料，不处理业务。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout
from .avatar import AvatarPortrait
from .scrapbook import ScrapbookCard
from ..palette import P


class ProfileHero(ScrapbookCard):
    def __init__(self, parent=None):
        super().__init__('lavender', parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 20, 30, 23)
        row.setSpacing(22)
        self.avatar = AvatarPortrait(126)
        row.addWidget(self.avatar, 0, Qt.AlignVCenter)
        identity = QVBoxLayout()
        identity.setSpacing(7)
        eyebrow = QLabel('SARIANA  /  我的键盘人设')
        eyebrow.setProperty('textRole', 'paperMuted')
        identity.addWidget(eyebrow)
        self.nickname = QLabel()
        self.nickname.setStyleSheet(f'color: {P.paper_text}; font-size: 26px; font-weight: 600;')
        identity.addWidget(self.nickname)
        level = QHBoxLayout()
        self.level_badge = QLabel('Lv.1')
        self.level_label = QLabel()
        self.level_label.setWordWrap(True)
        self.level_label.setProperty('textRole', 'paperMuted')
        level.addWidget(self.level_badge)
        level.addWidget(self.level_label, 1)
        identity.addLayout(level)
        self.signature = QLabel()
        self.signature.setWordWrap(True)
        self.signature.setProperty('textRole', 'paperMuted')
        identity.addWidget(self.signature)
        row.addLayout(identity, 1)
        aside = QVBoxLayout()
        self.actions = aside
        aside.setContentsMargins(5, 18, 0, 0)
        aside.setSpacing(14)
        self.streak = QLabel()
        aside.addWidget(self.streak, 0, Qt.AlignRight)
        quote = QLabel('“才没有在等你。\n只是键盘刚好空着。”')
        quote.setProperty('textRole', 'paperMuted')
        quote.setWordWrap(True)
        quote.setFixedWidth(152)
        aside.addWidget(quote)
        aside.addStretch()
        row.addLayout(aside)
