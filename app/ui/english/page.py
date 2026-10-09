"""独立英语入口：组件装配、可失效请求与服务调用。"""
import time
import uuid
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget
from ...english.service import EnglishSaveError, EnglishService
from ..palette import P
from ..widgets.design import PaperPage, PageHeading
from .library import LibraryPanel
from .spelling import SpellingPanel
from .sentences import SentencePanel
from .requests import SentenceRequest


class EnglishPage(PaperPage):
    result_saved = Signal(dict)
    running_changed = Signal(bool)
    settings_requested = Signal()

    def __init__(self, repo, balance, ai_service, parent=None, *, test_session=None):
        super().__init__(parent)
        self.service = EnglishService(repo, test_session=test_session)
        self._balance, self._ai_service = balance, ai_service
        self._mode = 'spelling'
        self._running = False
        self._request = None
        self._targets = ()
        self._sentence_run = None
        heading = PageHeading('把新词，\n敲成小星星', 'WORD / PLAY   ·   中文释义 → 英文拼写 · AI 语句 · 待复习')
        heading.title.setStyleSheet('font:36px "KaiTi"; color:#EEE5D6; background:transparent;')
        self.set_header(heading)
        self.body.setContentsMargins(30, 25, 30, 30)
        self.body.setSpacing(15)
        modes = QHBoxLayout()
        self.mode_buttons = {}
        self._mode_group = QButtonGroup(self)
        for mode, title in [('spelling', '单词拼写'), ('sentence', 'AI 语句'), ('review', '待复习')]:
            button = QPushButton(title)
            button.setCheckable(True)
            button.setProperty('growthTab', True)
            self._mode_group.addButton(button)
            button.clicked.connect(lambda checked=False, key=mode: self._set_mode(key))
            self.mode_buttons[mode] = button
            modes.addWidget(button)
        self.mode_buttons['spelling'].setChecked(True)
        modes.addStretch()
        note = QLabel('一点一点，把陌生敲熟。')
        note.setProperty('textRole', 'paperMuted')
        modes.addWidget(note)
        self.body.addLayout(modes)
        row = QHBoxLayout()
        row.setSpacing(23)
        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(505)
        self.spelling = SpellingPanel()
        self.sentences = SentencePanel()
        self.stack.addWidget(self.spelling)
        self.stack.addWidget(self.sentences)
        row.addWidget(self.stack, 1)
        self.library = LibraryPanel()
        sidebar = QWidget()
        offset = QVBoxLayout(sidebar)
        offset.setContentsMargins(0, 24, 0, 0)
        offset.addWidget(self.library, 0, Qt.AlignTop)
        offset.addStretch()
        row.addWidget(sidebar, 0)
        self.body.addLayout(row)
        self.library.deck_changed.connect(self._deck_changed)
        self.spelling.start_requested.connect(self._start_spelling)
        self.spelling.submit_requested.connect(self._submit_spelling)
        self.spelling.hint_requested.connect(self._hint)
        self.spelling.reveal_requested.connect(self._reveal)
        self.sentences.generate_requested.connect(self._generate)
        self.sentences.targets_requested.connect(self._choose_targets)
        self.sentences.settings_requested.connect(self.settings_requested.emit)
        self.sentences.start_requested.connect(self._start_sentence)
        self.sentences.finish_requested.connect(self._finish_sentence)
        self.sentences.material_changed.connect(self._reset_sentence)
        self.sentences.input.textChanged.connect(self._sentence_progress)
        self._deck_changed()

    def _set_running(self, running):
        if self._running != running:
            self._running = running
            self.running_changed.emit(running)

    def _set_mode(self, mode):
        self._cancel_request()
        self._reset_sentence()
        self.service.session = None
        self.spelling.set_active(False)
        self._set_running(False)
        self._mode = mode
        self.stack.setCurrentWidget(self.sentences if mode == 'sentence' else self.spelling)
        if mode == 'sentence':
            self.sentences.status.setText(self.service.ai_access(self._ai_service, self._balance)[1])
        self.spelling.progress.setText('只练还没记牢的词。' if mode == 'review' else '看中文，敲出英文。')

    def _deck_changed(self):
        self._cancel_request()
        self._reset_sentence()
        self.service.session = None
        self.spelling.set_active(False)
        self.spelling.meaning.setPlainText('词库已选好，开始新的一轮吧。')
        self._set_running(False)
        self._choose_targets()
        self.refresh()
        self.sentences.set_history(self.service.sentence_history(self.library.deck))

    def refresh(self):
        self.library.set_summary(self.service.summary(self.library.deck))
        self.library.avatar.set_preset(self.service.repo.get_setting('avatar_preset', 'default'))

    def _start_spelling(self):
        try:
            session = self.service.start(self.library.deck, self.library.count, review=self._mode == 'review')
        except ValueError as exc:
            self.spelling.feedback.setText(str(exc))
            return
        self._set_running(True)
        self.spelling.show_word(session.current, 0, len(session.words))
        self.spelling.start_button.setText('重新开始这一轮')

    def _submit_spelling(self):
        session = self.service.session
        if session is None or session.finished:
            return
        if session.result is not None:
            if self.service.advance():
                self._set_running(True)
                self.spelling.show_word(session.current, session.index, len(session.words))
            else:
                independent = sum(r['independent'] for r in session.results)
                self.spelling.set_active(False)
                self.spelling.feedback.setText(f'这一轮完成！独立答对 {independent} / {len(session.words)}。\n待复习词已经留好了，下次继续。')
                self._set_running(False)
                self.result_saved.emit({'id': f"spelling:{session.results[-1]['id']}",
                                        'accuracy': independent / max(1, len(session.words))})
            return
        try:
            result = self.service.submit(self.spelling.answer.text())
        except EnglishSaveError as exc:
            self.spelling.feedback.setText(str(exc))
            return
        if result.get('accepted'):
            self._set_running(False)
            self.spelling.show_result(session.current, result)
            self.refresh()
        elif result.get('error'):
            self.spelling.feedback.setText(result['error'])

    def _hint(self):
        first = self.service.hint()
        if first:
            self.spelling.feedback.setText(f'首字母是 {first}。这一题会记为辅助完成。')

    def _reveal(self):
        try:
            answer = self.service.reveal()
        except EnglishSaveError as exc:
            self.spelling.feedback.setText(str(exc))
            return
        if answer:
            session = self.service.session
            self._set_running(False)
            self.spelling.show_result(session.current, session.result)
            self.refresh()

    def _choose_targets(self):
        self._targets = tuple(w.word for w in self.service.catalog.sample(self.library.deck, 3))
        self.sentences.targets.setText('本轮目标词  /  ' + '  ·  '.join(self._targets))

    def _generate(self):
        if self._request is not None:
            return
        allowed, reason = self.service.ai_access(self._ai_service, self._balance)
        if not allowed:
            self.sentences.status.setText(reason)
            return
        self._reset_sentence()
        request = SentenceRequest(self._ai_service, self.library.deck, self._targets,
                                  self.sentences.topic.text().strip(), self,
                                  test_mode=self.service.test_session.enabled)
        request.done.connect(self._generated, Qt.QueuedConnection)
        self._request = request
        self.sentences.set_busy(True)
        self.sentences.usage_label.begin_request()
        self.sentences.status.setText('正在生成；只有有效材料保存成功才会使用训练券。')
        request.start()

    @Slot(str, bool, object)
    def _generated(self, request_id, ok, result):
        request = self._request
        if request is None or request_id != request.id or request.deck != self.library.deck:
            return
        self._request = None
        self.sentences.set_busy(False)
        self.sentences.usage_label.set_usage(request.usage)
        try:
            if not ok:
                self.sentences.status.setText(str(result))
                return
            self.service.save_generated(request.deck, request.topic, list(request.words), result,
                                        self._balance, test_mode=request.test_mode)
        except Exception as exc:
            self.sentences.status.setText(f'材料未保存，训练券未使用：{exc}')
            return
        finally:
            request.deleteLater()
        self.sentences.set_history(self.service.sentence_history(request.deck))
        self.sentences.status.setText('语句已经收好。选一句，开始跟打吧。')

    def _cancel_request(self):
        if self._request is not None:
            self.sentences.usage_label.set_usage(self._request.usage)
            self._request.cancel()
            self._request.deleteLater()
            self._request = None
            self.sentences.set_busy(False)
            self.sentences.status.setText('本次生成已取消，训练券未使用。')

    def _reset_sentence(self):
        self._sentence_run = None
        self.sentences.set_running(False)
        self._set_running(False)

    def _start_sentence(self):
        reference = self.sentences.reference_text
        if not reference or self._sentence_run is not None or self._request is not None:
            return
        self._sentence_run = (uuid.uuid4().hex, self.library.deck, reference, time.monotonic())
        self.sentences.set_running(True)
        self.sentences.status.setText('照着英文手动输入，完成后记录这一次。')
        self._set_running(True)

    def _finish_sentence(self):
        if self._sentence_run is None:
            return
        answer = self.sentences.input.toPlainText()
        if not answer.strip():
            self.sentences.status.setText('先输入句子，再记录这一次。')
            return
        event_id, deck, reference, started = self._sentence_run
        try:
            result = self.service.record_sentence(deck, reference, answer, time.monotonic() - started, event_id)
        except EnglishSaveError as exc:
            self.sentences.status.setText(str(exc))
            return
        self._reset_sentence()
        self.sentences.status.setText(f"这一句完成 · 正确率 {result['accuracy']:.1%} · 用时 {result['elapsed']:.1f} 秒")
        if result['saved']:
            self.result_saved.emit({'id': f'sentence:{event_id}', 'accuracy': result['accuracy']})

    def _sentence_progress(self):
        if self._sentence_run is not None:
            _, _, reference, _ = self._sentence_run
            count = len(self.sentences.input.toPlainText())
            self.sentences.status.setText(f'已输入 {count} / {len(reference)} 字符 · 完成后记录这一次')

    def set_motion_enabled(self, enabled):
        self.spelling.set_motion_enabled(enabled)

    def apply_theme(self):
        self.library.apply_theme()
        self.spelling.apply_theme()
        self.sentences.apply_theme()
        self.paper.update()

    def hideEvent(self, event):
        self._cancel_request()
        # 最小化、托盘与切页都保留题目/草稿；只有显式换模式或词库重置练习。
        self._set_running(False)
        self.set_motion_enabled(False)
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        session = self.service.session
        spelling_active = session is not None and not session.finished and session.result is None
        self._set_running(self._sentence_run is not None or spelling_active)
