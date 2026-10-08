"""只读个人练习榜：服务传入同篇记录，表格负责呈现与空状态。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from .scrapbook import ScrapbookCard
from ..palette import P


class PracticeLeaderboard(ScrapbookCard):
    def __init__(self, parent=None):
        super().__init__('lavender', parent)
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 26, 24)
        layout.setSpacing(8)
        self.title = QLabel('个人练习榜')
        self.title.setProperty('textRole', 'paperField')
        layout.addWidget(self.title)
        self.hint = QLabel('本机记录 · 仅比较同一范文 · 前 10 次成绩')
        self.hint.setProperty('textRole', 'paperMuted')
        self.hint.setWordWrap(True)
        self.hint.setToolTip('按单次综合分降序，平分时依次比较正确率、用时和记录时间。\n不包含缺少计分或用时的旧记录。')
        layout.addWidget(self.hint)
        self.empty = QLabel('榜首暂时空着。\n敲完这一篇，就让自己的名字上榜。')
        self.empty.setProperty('textRole', 'paperMuted')
        self.empty.setWordWrap(True)
        self.empty.setMinimumHeight(64)
        layout.addWidget(self.empty)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['名次', '综合分', '速度 tw/分', '正确率', '用时 秒', '记录时间'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setShowGrid(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(50)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setAccessibleName('同一范文的个人练习记录排行榜')
        self.table.horizontalHeaderItem(1).setToolTip(
            '综合分 = (速度×0.6 + 正确字数×0.1 + 正确率%×0.5) ×10000 ×完成系数。')
        layout.addWidget(self.table)
        self._records_key = None
        self.apply_theme()

    def apply_theme(self):
        self.table.setStyleSheet(f'''
QTableWidget {{ background: transparent; color: {P.paper_text}; border: none; font-size: 13px; }}
QTableWidget::item {{ border: none; padding: 3px; }}
QHeaderView::section {{ background: transparent; color: {P.paper_muted}; border: none;
    padding: 6px 3px; font-size: 13px; }}
''')
        self.update()

    def set_records(self, passage_name, records):
        key = (passage_name, tuple(tuple(row.get(field) for field in
                    ('id', 'score', 'speed', 'accuracy', 'elapsed_seconds', 'started_at'))
                    for row in records), P.primary, P.paper_text, P.paper_muted)
        if key == self._records_key:
            return
        self._records_key = key
        self.title.setText(f'个人练习榜 · {passage_name}')
        self.title.setWordWrap(True)
        self.table.setRowCount(len(records))
        self.empty.setVisible(not records)
        self.table.setVisible(bool(records))
        for i, record in enumerate(records):
            values = (f'{record["rank"]:02}', f'{record["score"]:,.0f}',
                      f'{record["speed"]:.1f}', f'{record["accuracy"] * 100:.1f}%',
                      f'{record["elapsed_seconds"]:.1f}', record['started_at'].replace('T', ' ')[5:16])
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignVCenter | (Qt.AlignRight if col in (1, 2, 3, 4) else Qt.AlignCenter))
                item.setToolTip(record['started_at'] if col == 5 else value)
                if i == 0:
                    item.setBackground(QColor(P.primary))
                    item.setForeground(QColor(P.primary_text))
                self.table.setItem(i, col, item)
        self.table.setFixedHeight(36 * len(records) + 36)
        self.apply_theme()
