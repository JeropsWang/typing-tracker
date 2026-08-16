"""打字竞速挑战页：范文对照输入 → 逐字高亮 → 实时指标 → 成绩与历史最佳。

- 正确率 = 与原文逐字对比（精确口径，区别于全局按键近似）
- 挑战中的输入会计入今日全局统计（说明见页面提示）
"""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ...core.challenge import TEXT_BY_ID, TEXTS, score
from ..palette import P


class ChallengePage(QWidget):
    def __init__(self, repo, balance, challenge_svc, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._balance = balance
        self._svc = challenge_svc
        self._running = False
        self._start_ts = 0.0
        self._elapsed = 0.0

        root = QVBoxLayout(self)

        # 顶栏
        top = QHBoxLayout()
        top.addWidget(QLabel('文本:'))
        self._text_combo = QComboBox()
        for t in TEXTS:
            self._text_combo.addItem(t['name'], t['id'])
        self._text_combo.currentIndexChanged.connect(self._reset)
        top.addWidget(self._text_combo)
        self._start_btn = QPushButton('开始挑战 ⚡')
        self._start_btn.clicked.connect(self._start)
        top.addWidget(self._start_btn)
        self._reset_btn = QPushButton('重来')
        self._reset_btn.setEnabled(False)
        self._reset_btn.clicked.connect(self._reset)
        top.addWidget(self._reset_btn)
        top.addStretch(1)
        root.addLayout(top)

        # 参考文本（逐字高亮）
        ref_head = QHBoxLayout()
        rt = QLabel('📄 参考文本')
        rt.setStyleSheet('font-size:13px; font-weight:700;')
        ref_head.addWidget(rt)
        ref_head.addStretch(1)
        self._hint_label = QLabel('')
        self._hint_label.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        ref_head.addWidget(self._hint_label)
        root.addLayout(ref_head)

        self._ref_label = QLabel('')
        self._ref_label.setWordWrap(True)
        self._ref_label.setTextFormat(Qt.RichText)
        self._ref_label.setStyleSheet(
            'font-size:17px; line-height:150%; padding:12px;'
            f'background:{P.card_bg}; border-radius:12px;'
            f'border:1px solid {P.card_border};')
        root.addWidget(self._ref_label)

        # 输入区
        self._input = QPlainTextEdit()
        self._input.setPlaceholderText('点击「开始挑战」后在此输入…')
        self._input.setEnabled(False)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.setStyleSheet(
            f'font-size:17px; padding:10px;'
            f'background:{P.card_bg}; border-radius:12px;'
            f'border:1px solid {P.card_border};')
        root.addWidget(self._input, 1)

        # 状态条
        status = QHBoxLayout()
        self._time_label = QLabel('⏱ 0.0s')
        self._time_label.setStyleSheet('font-size:15px; font-weight:700;')
        status.addWidget(self._time_label)
        self._speed_label = QLabel('⚡ 0.0 tw/分')
        self._speed_label.setStyleSheet('font-size:15px; font-weight:700;')
        status.addWidget(self._speed_label)
        self._acc_label = QLabel('🎯 100%')
        self._acc_label.setStyleSheet('font-size:15px; font-weight:700;')
        status.addWidget(self._acc_label)
        self._prog_label = QLabel('0%')
        self._prog_label.setStyleSheet(f'color:{P.muted}; font-size:13px;')
        status.addWidget(self._prog_label)
        status.addStretch(1)
        root.addLayout(status)

        # 结果面板
        self._result = QFrame()
        self._result.setFrameShape(QFrame.StyledPanel)
        rv = QVBoxLayout(self._result)
        self._result_title = QLabel('')
        self._result_title.setStyleSheet('font-size:18px; font-weight:800;')
        self._result_title.setAlignment(Qt.AlignCenter)
        rv.addWidget(self._result_title)
        self._result_detail = QLabel('')
        self._result_detail.setStyleSheet(f'color:{P.muted}; font-size:13px;')
        self._result_detail.setAlignment(Qt.AlignCenter)
        rv.addWidget(self._result_detail)
        self._result.setVisible(False)
        root.addWidget(self._result)

        # 近期记录
        self._recent_label = QLabel('')
        self._recent_label.setStyleSheet(f'color:{P.muted}; font-size:11px;')
        self._recent_label.setWordWrap(True)
        root.addWidget(self._recent_label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._render_reference('')
        self._refresh_recent()
        self.apply_theme()

    def apply_theme(self):
        self._ref_label.setStyleSheet(
            'font-size:17px; padding:12px;'
            f'background:{P.card_bg}; border-radius:12px;'
            f'border:1px solid {P.card_border};')
        self._input.setStyleSheet(
            f'font-size:17px; padding:10px;'
            f'background:{P.card_bg}; border-radius:12px;'
            f'border:1px solid {P.card_border};')
        self._hint_label.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        self._result_detail.setStyleSheet(f'color:{P.muted}; font-size:13px;')
        self._prog_label.setStyleSheet(f'color:{P.muted}; font-size:13px;')

    # ---------- 流程 ----------
    def _current_text(self) -> str:
        return TEXT_BY_ID[self._text_combo.currentData()]['text']

    def _start(self):
        self._reset()
        self._running = True
        self._start_ts = time.monotonic()
        self._input.setEnabled(True)
        self._input.setFocus()
        self._start_btn.setEnabled(False)
        self._reset_btn.setEnabled(True)
        self._timer.start(100)
        self._hint_label.setText('挑战输入会计入今日统计 · 打完自动结算')

    def _reset(self, *_):
        self._running = False
        self._timer.stop()
        self._input.setEnabled(False)
        self._input.clear()
        self._start_btn.setEnabled(True)
        self._reset_btn.setEnabled(False)
        self._time_label.setText('⏱ 0.0s')
        self._speed_label.setText('⚡ 0.0 tw/分')
        self._acc_label.setText('🎯 100%')
        self._prog_label.setText('0%')
        self._result.setVisible(False)
        self._render_reference('')
        self._refresh_recent()

    def _tick(self):
        if self._running:
            self._elapsed = time.monotonic() - self._start_ts
            self._time_label.setText(f'⏱ {self._elapsed:.1f}s')

    def _on_text_changed(self):
        inp = self._input.toPlainText()
        ref = self._current_text()
        self._render_reference(inp)

        if not self._running:
            return
        total = len(ref) or 1
        self._prog_label.setText(f'{min(100, int(len(inp) / total * 100))}%')
        if inp:
            s = score(inp, ref, time.monotonic() - self._start_ts, self._balance)
            self._speed_label.setText(f'⚡ {s["speed"]:.1f} tw/分')
            self._acc_label.setText(f'🎯 {s["accuracy"] * 100:.1f}%')
        # 完成检测
        if inp and len(inp) >= len(ref):
            self._finish(inp, ref)

    def _finish(self, inp, ref):
        self._running = False
        self._timer.stop()
        self._elapsed = time.monotonic() - self._start_ts
        s = score(inp, ref, self._elapsed, self._balance)
        s['elapsed_seconds'] = self._elapsed
        r = self._svc.record(self._text_combo.currentData(), s, self._balance)

        name = TEXT_BY_ID[self._text_combo.currentData()]['name']
        if r['is_best']:
            self._result_title.setText('🎉 新纪录！')
            self._result_title.setStyleSheet(
                f'font-size:20px; font-weight:900; color:{P.warn};')
        else:
            self._result_title.setText('挑战完成！')
            self._result_title.setStyleSheet('font-size:20px; font-weight:800;')
        self._result_detail.setText(
            f'{name}　·　用时 {self._elapsed:.1f}s　·　'
            f'速度 {s["speed"]:.1f} tw/分　·　正确率 {s["accuracy"] * 100:.1f}%\n'
            f'历史最佳 {r["prev_best"]:.0f} tw/分'
            + ('　← 就是你！' if r['is_best'] else ''))
        self._result.setVisible(True)
        self._input.setEnabled(False)
        self._hint_label.setText('点「重来」再战一次')
        self._refresh_recent()

    # ---------- 渲染 ----------
    def _render_reference(self, inp: str):
        ref = self._current_text()
        parts = []
        for i, ch in enumerate(ref):
            if i < len(inp):
                if inp[i] == ch:
                    style = f'color:{P.success};'
                else:
                    style = f'color:#ef4444; text-decoration:underline;'
            else:
                style = f'color:{P.muted};'
            parts.append(f'<span style="{style}">{html.escape(ch)}</span>')
        self._ref_label.setText(''.join(parts))

    def _refresh_recent(self):
        rows = self._svc.recent(6)
        if not rows:
            self._recent_label.setText('近期挑战：暂无记录，来一次吧 ⚡')
            return
        lines = []
        for r in rows:
            name = TEXT_BY_ID.get(r['text_id'], {}).get('name', r['text_id'])
            mark = ' 👑' if r['best'] else ''
            lines.append(
                f'{name} · {r["elapsed_seconds"]:.1f}s · {r["tw"]:.0f} tw · '
                f'{r["accuracy"] * 100:.0f}%{mark}')
        self._recent_label.setText('🕘 近期挑战：' + '　|　'.join(lines))
