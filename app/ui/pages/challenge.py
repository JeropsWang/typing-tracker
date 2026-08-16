"""打字竞速挑战页：范文对照输入 → 逐字高亮 → 实时指标 → 成绩与历史最佳。

- 正确率 = 与原文逐字对比（精确口径，区别于全局按键近似）
- 文本来源：内置范文 + AI 生成（OpenAI 兼容 / Ollama 本地，可持久化）
- 挑战中的输入会计入今日全局统计（说明见页面提示）
"""
from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ...core.challenge import TEXTS, ai_access_state, score
from ...services.exp_service import level_and_progress
from ..palette import P


class _ChallengeInput(QPlainTextEdit):
    """挑战输入框：运行中禁止粘贴（防刷分；IME 整句上屏不受影响）。"""

    paste_blocked = Signal()

    def insertFromMimeData(self, source):
        self.paste_blocked.emit()


class _GenThread(QThread):
    """AI 范文生成线程：done(ok, text, err)"""

    done = Signal(bool, str, str)

    def __init__(self, ai_svc, topic, lang, length, parent=None):
        super().__init__(parent)
        self._svc = ai_svc
        self._topic = topic
        self._lang = lang
        self._length = length

    def run(self):
        try:
            ok, res = self._svc.generate(self._topic, self._lang, self._length)
            self.done.emit(ok, res if ok else '', '' if ok else res)
        except Exception as e:
            self.done.emit(False, '', str(e))


class ChallengePage(QWidget):
    confetti_requested = Signal(int)    # 彩带庆祝（1=金色 2=多彩）

    def __init__(self, repo, balance, challenge_svc, ai_service=None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._balance = balance
        self._svc = challenge_svc
        self._ai = ai_service
        self._running = False
        self._start_ts = 0.0
        self._elapsed = 0.0
        self._gen_thread = None

        root = QVBoxLayout(self)

        # 顶栏：文本选择 / 开始 / 重来
        top = QHBoxLayout()
        top.addWidget(QLabel('文本:'))
        self._text_combo = QComboBox()
        self._text_combo.currentIndexChanged.connect(self._reset)
        top.addWidget(self._text_combo, 1)
        self._start_btn = QPushButton('开始挑战 ⚡')
        self._start_btn.clicked.connect(self._start)
        top.addWidget(self._start_btn)
        self._reset_btn = QPushButton('重来')
        self._reset_btn.setEnabled(False)
        self._reset_btn.clicked.connect(self._reset)
        top.addWidget(self._reset_btn)
        root.addLayout(top)

        # AI 定制训练行（Lv.45 解锁 / AI 训练券提前体验）
        if self._ai is not None:
            ai_row = QHBoxLayout()
            self._topic_edit = QLineEdit()
            self._topic_edit.setPlaceholderText('AI 定制训练主题（如：星空 / 未来城市 / 美食）')
            self._topic_edit.returnPressed.connect(self._ai_generate)
            ai_row.addWidget(self._topic_edit, 1)
            self._lang_combo = QComboBox()
            self._lang_combo.addItem('中文', 'cn')
            self._lang_combo.addItem('English', 'en')
            ai_row.addWidget(self._lang_combo)
            self._ai_btn = QPushButton('✨ AI 生成范文')
            self._ai_btn.clicked.connect(self._ai_generate)
            ai_row.addWidget(self._ai_btn)
            self._ai_status = QLabel('')
            self._ai_status.setStyleSheet(f'color:{P.faint}; font-size:11px;')
            ai_row.addWidget(self._ai_status)
            root.addLayout(ai_row)
            self.update_ai_access()

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
            'font-size:17px; padding:12px;'
            f'background:{P.card_bg}; border-radius:12px;'
            f'border:1px solid {P.card_border};')
        root.addWidget(self._ref_label)

        # 输入区（挑战中禁粘贴，防刷分）
        self._input = _ChallengeInput()
        self._input.paste_blocked.connect(self._on_paste_blocked)
        self._input.setPlaceholderText('点击「开始挑战」后在此输入…（挑战中禁止粘贴）')
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
        self._result_title.setAlignment(Qt.AlignCenter)
        rv.addWidget(self._result_title)
        # 百万级大数字：分数滚动动画（不使用 QGraphicsEffect，避免无边框
        # 透明窗口上的渲染偏移问题）
        self._score_label = QLabel('0')
        self._score_label.setAlignment(Qt.AlignCenter)
        self._score_label.setStyleSheet(
            f'font-size:60px; font-weight:900; color:{P.warn};')
        rv.addWidget(self._score_label)
        self._score_unit = QLabel('SCORE')
        self._score_unit.setAlignment(Qt.AlignCenter)
        self._score_unit.setStyleSheet(
            f'color:{P.faint}; font-size:12px; font-weight:700; letter-spacing:4px;')
        rv.addWidget(self._score_unit)
        self._result_detail = QLabel('')
        self._result_detail.setStyleSheet(f'color:{P.muted}; font-size:13px;')
        self._result_detail.setAlignment(Qt.AlignCenter)
        rv.addWidget(self._result_detail)
        self._result.setVisible(False)
        root.addWidget(self._result)

        self._score_anim = QTimer(self)
        self._score_anim.timeout.connect(self._tick_score)
        self._score_now = 0
        self._score_target = 0

        # 近期记录
        self._recent_label = QLabel('')
        self._recent_label.setStyleSheet(f'color:{P.muted}; font-size:11px;')
        self._recent_label.setWordWrap(True)
        root.addWidget(self._recent_label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._reload_texts()
        self._refresh_recent()
        self.apply_theme()

    # ---------- 文本库 ----------
    def _reload_texts(self):
        self._texts = list(TEXTS)
        for row in self._repo.list_ai_texts():
            self._texts.append({
                'id': f'ai:{row["id"]}',
                'name': f'AI · {row["topic"]}',
                'lang': row['lang'],
                'text': row['text'],
            })
        self._text_combo.blockSignals(True)
        self._text_combo.clear()
        for t in self._texts:
            self._text_combo.addItem(t['name'], t['id'])
        self._text_combo.blockSignals(False)
        self._reset()

    def _current_text(self) -> str:
        tid = self._text_combo.currentData()
        for t in self._texts:
            if t['id'] == tid:
                return t['text']
        return self._texts[0]['text']

    def _text_name(self, tid: str) -> str:
        for t in self._texts:
            if t['id'] == tid:
                return t['name']
        return tid

    # ---------- AI 定制训练 ----------
    def update_ai_access(self):
        """等级/训练券访问控制（升级后由主窗口调用刷新）。"""
        if self._ai is None:
            return
        if not self._ai.enabled():
            self._ai_btn.setEnabled(False)
            self._topic_edit.setEnabled(False)
            self._ai_status.setText('AI 未启用：设置 → AI 配置（支持 OpenAI 兼容 / Ollama）')
            self._ai_status.setStyleSheet('color:#ef4444; font-size:11px;')
            return
        level, _, _ = level_and_progress(self._repo.get_exp(), self._balance)
        passes = self._repo.count_ai_passes()
        unlock = self._balance.get('ai', {}).get('unlock_level', 45)
        allowed, hint = ai_access_state(level, passes, unlock)
        self._ai_btn.setEnabled(allowed)
        self._topic_edit.setEnabled(allowed)
        self._ai_status.setText(hint)
        self._ai_status.setStyleSheet(
            f'color:{P.success if allowed else P.warn}; font-size:11px;')

    def _ai_generate(self):
        if self._gen_thread is not None and self._gen_thread.isRunning():
            return
        topic = self._topic_edit.text().strip()
        if not topic:
            self._ai_status.setText('请先输入主题 ✍️')
            return
        # 生成前预检库存：曾等生成成功后才扣券，券不足时 API 已计费而文本
        # 被丢弃（v0.8.9 修复）
        level, _, _ = level_and_progress(self._repo.get_exp(), self._balance)
        unlock = self._balance.get('ai', {}).get('unlock_level', 45)
        if level < unlock and self._repo.count_ai_passes() <= 0:
            self._ai_status.setText('❌ AI 训练券不足（速度跃升可获得训练券）')
            self._ai_status.setStyleSheet('color:#ef4444; font-size:11px;')
            return
        self._ai_btn.setEnabled(False)
        self._ai_status.setText('生成中…（本地模型可能较慢）')
        self._gen_thread = _GenThread(self._ai, topic,
                                      self._lang_combo.currentData(), 260, self)
        self._gen_thread.done.connect(self._ai_done)
        self._gen_thread.start()

    def _ai_done(self, ok, text, err):
        self._ai_btn.setEnabled(True)
        if not ok:
            self._ai_status.setText(f'❌ {err}')
            self._ai_status.setStyleSheet('color:#ef4444; font-size:11px;')
            return
        # 未满 45 级时消耗 AI 训练券（满级后无限生成）
        level, _, _ = level_and_progress(self._repo.get_exp(), self._balance)
        unlock = self._balance.get('ai', {}).get('unlock_level', 45)
        if level < unlock and not self._repo.use_reward('ai_pass'):
            self._ai_status.setText('❌ 训练券不足，无法生成')
            self._ai_status.setStyleSheet('color:#ef4444; font-size:11px;')
            return
        topic = self._topic_edit.text().strip()
        lang = self._lang_combo.currentData()
        self._repo.add_ai_text(lang, topic, text)
        self._ai_status.setText(f'✅ 已生成并加入文本库：{topic}')
        self._ai_status.setStyleSheet(f'color:{P.success}; font-size:11px;')
        self._reload_texts()
        self.update_ai_access()
        # 选中刚生成的文本
        for i, t in enumerate(self._texts):
            if t['id'].startswith('ai:') and t['name'].endswith(topic):
                self._text_combo.setCurrentIndex(i)
                break

    # ---------- 主题 ----------
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
        if self._ai is not None:
            self._ai_status.setStyleSheet(f'color:{P.faint}; font-size:11px;')

    # ---------- 流程 ----------
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
        self._score_anim.stop()
        self._score_now = 0
        self._score_target = 0
        self._render_reference('')
        self._refresh_recent()

    def _on_paste_blocked(self):
        if self._running:
            self._hint_label.setText('❌ 挑战中禁止粘贴——请手动输入！')

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

        name = self._text_name(self._text_combo.currentData())
        if r['is_best']:
            self._result_title.setText('🎉 新纪录！')
            self._result_title.setStyleSheet(
                f'font-size:22px; font-weight:900; color:{P.warn};')
        else:
            self._result_title.setText('挑战完成！')
            self._result_title.setStyleSheet('font-size:20px; font-weight:800;')
        self._result_detail.setText(
            f'速度 {s["speed"]:.1f} tw/分　·　正确率 {s["accuracy"] * 100:.1f}%　·　'
            f'用时 {self._elapsed:.1f}s　·　有效 {s["typed_chars"] - s["errors"]} 字\n'
            f'公式：速度×0.6 + 字数×0.1 + 正确率%×0.5，×10000 × 完成系数\n'
            f'历史最佳 {r["prev_best"]:,} 分'
            + ('　← 你刚刷新了纪录！' if r['is_best'] else '')
            + (f'　·　+{r["exp_gained"]} 经验' if r.get('exp_gained') else ''))
        self._result.setVisible(True)
        # 分数档位彩带：≥100万金色，≥200万多彩
        if s['score_points'] >= 1_000_000:
            self.confetti_requested.emit(2 if s['score_points'] >= 2_000_000 else 1)
        self._input.setEnabled(False)
        self._hint_label.setText('点「重来」再战一次')
        self._refresh_recent()
        # 分数滚动动画（百万级大数字）
        self._score_now = 0
        self._score_target = s['score_points']
        self._score_label.setText(f'{self._score_now:,}')
        self._score_anim.start(24)

    def _tick_score(self):
        """分数从 0 滚动到目标（约 1.2s 完成）。"""
        step = max(1, self._score_target // 50)
        self._score_now = min(self._score_target, self._score_now + step)
        self._score_label.setText(f'{self._score_now:,}')
        if self._score_now >= self._score_target:
            self._score_anim.stop()

    # ---------- 渲染 ----------
    def _render_reference(self, inp: str):
        ref = self._current_text()
        parts = []
        for i, ch in enumerate(ref):
            if i < len(inp):
                if inp[i] == ch:
                    style = f'color:{P.success};'
                else:
                    style = 'color:#ef4444; text-decoration:underline;'
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
            mark = ' 👑' if r['best'] else ''
            lines.append(
                f'{self._text_name(r["text_id"])} · {r["score"]:.0f}分 · '
                f'{r["elapsed_seconds"]:.1f}s · {r["accuracy"] * 100:.0f}%{mark}')
        self._recent_label.setText('🕘 近期挑战：' + '　|　'.join(lines))
