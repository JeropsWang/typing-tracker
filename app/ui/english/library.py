"""词库便签：选择与进度展示，不访问数据库。"""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout
from ...english.catalog import DECKS
from ..widgets.avatar import AvatarPortrait
from ..widgets.scrapbook import ScrapbookCard
from ..palette import P


class LibraryPanel(ScrapbookCard):
    deck_changed = Signal()

    def __init__(self, parent=None):
        super().__init__('rose', parent)
        self.setFixedWidth(254)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 29, 27, 27)
        layout.setSpacing(12)
        title = QLabel('今晚，学哪一本？')
        title.setProperty('textRole', 'paperField')
        layout.addWidget(title)
        self.deck_combo = QComboBox()
        for key, label in DECKS.items():
            self.deck_combo.addItem(label, key)
        self.deck_combo.currentIndexChanged.connect(lambda _: self.deck_changed.emit())
        layout.addWidget(self.deck_combo)
        layout.addWidget(QLabel('每轮词数'))
        self.round_combo = QComboBox()
        for n in (10, 20, 50):
            self.round_combo.addItem(f'{n} 个词', n)
        self.round_combo.setCurrentIndex(1)
        layout.addWidget(self.round_combo)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.avatar = AvatarPortrait(86)
        layout.addWidget(self.avatar, 0, Qt.AlignLeft)
        quote = QLabel('才没有催你。\n只是下一个词在等你。')
        quote.setProperty('textRole', 'paperMuted')
        layout.addWidget(quote)
        source = QLabel('ECDICT · 备考参考词库\n释义与音标以源数据为准')
        source.setProperty('textRole', 'paperMuted')
        source.setWordWrap(True)
        layout.addWidget(source)
        self.apply_theme()

    @property
    def deck(self):
        return self.deck_combo.currentData()

    @property
    def count(self):
        return self.round_combo.currentData()

    def set_summary(self, result):
        accuracy = result['accuracy']
        rate = '—' if accuracy is None else f'{accuracy:.0%}'
        self.summary.setText(f"已练 {result['trained']} 词 · 待复习 {result['review_count']}\n独立答对率 {rate}")

    def apply_theme(self):
        self.setStyleSheet(f'LibraryPanel QLabel {{color:{P.paper_text}; background:transparent;}}')
        self.update()
