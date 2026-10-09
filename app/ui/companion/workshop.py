"""Offline creation gallery, explicit draft/save/apply workflow and portable sharing."""
import copy
from pathlib import Path
import shutil
import tempfile
import uuid
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QFileDialog, QMessageBox,
    QScrollArea, QTabWidget, QSplitter, QMenu,
)
from ...companion.validation import image_size, safe_path
from .editor import StateEditor
from .preview import CreationPreview
from .artwork import sprite_icon

STYLE = '''
QDialog#companionWorkshop {background:#F8F4EC;color:#4F405D;}
QDialog#companionWorkshop QWidget {font-family:"Microsoft YaHei UI";font-size:14px;color:#4F405D;}
QDialog#companionWorkshop QLabel {background:transparent;}
QDialog#companionWorkshop QLabel[companionHeading="true"] {font-size:16px;font-weight:600;}
QDialog#companionWorkshop QLabel[companionHint="true"] {color:#75677C;font-size:12px;}
QDialog#companionWorkshop QLineEdit, QDialog#companionWorkshop QPlainTextEdit,
QDialog#companionWorkshop QComboBox, QDialog#companionWorkshop QSpinBox {
 background:#FFFCF7;color:#4F405D;border:1px solid #D9CFDF;border-radius:8px;padding:6px;min-height:24px;}
QDialog#companionWorkshop QLineEdit#companionCreationName {font-family:"SimSun";font-size:25px;font-weight:700;background:transparent;border:0;padding:0;}
QDialog#companionWorkshop QListWidget {background:transparent;border:0;padding:0;outline:0;}
QDialog#companionWorkshop QListWidget::item {padding:10px 4px;min-height:48px;border-radius:9px;}
QDialog#companionWorkshop QListWidget::item:selected {background:#E3D9E9;color:#392B47;}
QDialog#companionWorkshop QPushButton, QDialog#companionWorkshop QToolButton {background:#F4EEF3;color:#4F405D;border:1px solid #DBD0E0;border-radius:8px;padding:7px 10px;min-height:24px;}
QDialog#companionWorkshop QPushButton:hover, QDialog#companionWorkshop QToolButton:hover {background:#E9DFED;}
QDialog#companionWorkshop QPushButton[companionState="true"] {padding:5px 2px;background:#FCF8F2;}
QDialog#companionWorkshop QPushButton:checked, QDialog#companionWorkshop QToolButton:checked {background:#DED1E8;border:1px solid #A58AB8;}
QDialog#companionWorkshop QPushButton[companionQuiet="true"] {background:transparent;border:0;padding:5px 6px;}
QDialog#companionWorkshop QPushButton[companionPrimary="true"] {background:#675177;color:#FFF9F0;border:1px solid #675177;font-weight:600;padding:9px 22px;}
QDialog#companionWorkshop QPushButton:disabled {color:#867B89;background:#EEE8EB;border-color:#E4DBE5;}
QDialog#companionWorkshop QFrame#companionDialoguePaper {background:#FFFCF7;border:1px solid #F0E8DF;border-radius:10px;}
QDialog#companionWorkshop QPlainTextEdit#companionDialogueLines {background:transparent;border:0;padding:3px;}
QDialog#companionWorkshop QSplitter::handle {background:transparent;width:14px;}
QDialog#companionWorkshop QPushButton:focus, QDialog#companionWorkshop QToolButton:focus {border:2px solid #9476A7;}
QDialog#companionWorkshop QScrollArea {background:transparent;border:0;}
QDialog#companionWorkshop QTabWidget::pane {border:0;background:transparent;}
QDialog#companionWorkshop QTabBar::tab {background:#E3D9E7;color:#65536F;padding:9px 18px;border-radius:9px;}
QDialog#companionWorkshop QTabBar::tab:selected {background:#746080;color:#FFF9F0;}
'''


class Workshop(QDialog):
    def __init__(self, store, controller, parent=None):
        super().__init__(parent)
        self.setObjectName('companionWorkshop')
        self.setWindowTitle('Sariana · 本地二创工坊')
        self.setModal(False)
        self.setStyleSheet(STYLE)
        area = self.screen().availableGeometry()
        self.resize(min(1120, area.width() - 40), min(760, area.height() - 60))
        self.setMinimumSize(min(650, area.width() - 40), min(540, area.height() - 60))
        self.store, self.controller = store, controller
        self.draft = None
        self.assets = {}
        self.selected_id = controller.pack.id
        self.dirty = False
        self.editable = False
        self._loading = False
        self._narrow = None
        self._temp = tempfile.TemporaryDirectory(prefix='sariana-draft-')
        self.destroyed.connect(lambda: self._temp.cleanup())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(10)
        self.description = QLabel('把她的每一种心情，改成你喜欢的样子。作品都保存在本机。')
        self.description.setProperty('companionHint', True)
        self.description.setWordWrap(True)
        self.wide = QSplitter(Qt.Horizontal)
        self.wide.setChildrenCollapsible(False)
        self.tabs = QTabWidget()
        self.tabs.hide()
        layout.addWidget(self.wide, 1)
        layout.addWidget(self.tabs, 1)

        gallery = QWidget()
        gl = QVBoxLayout(gallery)
        gl.setContentsMargins(0, 0, 6, 0)
        gl.setSpacing(12)
        title = QLabel('Sariana 创作室')
        title.setStyleSheet('font-family:"SimSun";font-size:20px;font-weight:700;')
        gl.addWidget(title)
        self.description.setText('把心情，变成你的表达。')
        gl.addWidget(self.description)
        gl.addSpacing(12)
        heading = QLabel('我的作品')
        heading.setProperty('companionHeading', True)
        gl.addWidget(heading)
        self.gallery = QListWidget()
        self.gallery.setIconSize(QSize(46, 54))
        self.gallery.setAccessibleName('本地角色作品列表')
        self.gallery.currentItemChanged.connect(self._selection_changed)
        gl.addWidget(self.gallery, 1)
        gallery_actions = QHBoxLayout()
        copy_button = QPushButton('复制作品')
        copy_button.setToolTip('复制为我的作品，再开始编辑')
        copy_button.clicked.connect(self.copy_draft)
        gallery_actions.addWidget(copy_button, 1)
        more_button = QPushButton('更多')
        menu = QMenu(more_button)
        for label, slot in [('从模板新建', self.new_draft), ('导入作品包…', self.import_pack),
                            ('导出选中作品…', self.export_pack), ('删除我的作品', self.delete_pack)]:
            menu.addAction(label, slot)
        more_button.setMenu(menu)
        gallery_actions.addWidget(more_button)
        gl.addLayout(gallery_actions)

        edit_panel = QWidget()
        el = QVBoxLayout(edit_panel)
        el.setContentsMargins(4, 0, 6, 0)
        el.setSpacing(10)
        label = QLabel('手帐工作台')
        label.setProperty('companionHint', True)
        el.addWidget(label)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName('companionCreationName')
        self.name_edit.setAccessibleName('作品名称')
        self.name_edit.setMaxLength(60)
        self.author_edit = QLineEdit()
        self.author_edit.setMaxLength(60)
        self.desc_edit = QLineEdit()
        self.desc_edit.setMaxLength(500)
        for text, widget in [('作品名称', self.name_edit), ('作者', self.author_edit), ('简介', self.desc_edit)]:
            if widget is self.name_edit:
                el.addWidget(widget)
            else:
                form.addRow(text, widget)
            widget.textChanged.connect(self._changed)
        information = QWidget()
        information.setLayout(form)
        form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        self.info_button = QPushButton('作品信息')
        self.info_button.setCheckable(True)
        self.info_button.setProperty('companionQuiet', True)
        self.info_button.toggled.connect(information.setVisible)
        gl.addWidget(self.info_button)
        gl.addWidget(information)
        information.hide()
        self.editor = StateEditor()
        self.editor.changed.connect(self._changed)
        self.editor.selection_changed.connect(self._preview_current)
        self.editor.replace_requested.connect(self.choose_asset)
        el.addWidget(self.editor, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(edit_panel)
        scroll.setMinimumWidth(340)
        self.preview = CreationPreview()
        self.preview.setMinimumWidth(350)
        self.preview.state_selected.connect(self.editor.select_state)
        self.preview.layout().removeItem(self.preview.controls)
        self.editor.timing.addWidget(self.preview.motion)
        self.editor.timing.addWidget(self.preview.simulate_button)
        self.editor.more.layout().addWidget(QLabel('模拟互动类型'))
        self.editor.more.layout().addWidget(self.preview.event)
        self.panels = (gallery, scroll, self.preview)
        self._reflow()
        self.wide.setSizes([180, 400, 460])

        self.feedback = QLabel('')
        self.feedback.setWordWrap(True)
        self.feedback.setMinimumHeight(24)
        self.feedback.setProperty('companionHint', True)
        actions = QHBoxLayout()
        actions.addWidget(self.feedback, 1)
        self.discard_button = QPushButton('放弃修改')
        self.discard_button.clicked.connect(self.discard_draft)
        actions.addWidget(self.discard_button)
        self.save_button = QPushButton('保存作品')
        self.save_button.setProperty('companionPrimary', True)
        self.save_button.clicked.connect(self.save_draft)
        actions.addWidget(self.save_button)
        self.apply_button = QPushButton('应用到小伙伴')
        self.apply_button.clicked.connect(self.apply_pack)
        actions.addWidget(self.apply_button)
        layout.addLayout(actions)
        self.refresh_gallery()
        self.load_pack(self.selected_id)

    def _reflow(self):
        if not hasattr(self, 'panels'):
            return
        narrow = self.width() < 1000
        if narrow == self._narrow:
            return
        self._narrow = narrow
        if narrow:
            for panel, title in zip(self.panels, ('作品', '编辑', '预览')):
                self.tabs.addTab(panel, title)
        else:
            while self.tabs.count():
                self.tabs.removeTab(0)
            for panel in self.panels:
                self.wide.addWidget(panel)
                panel.show()
            self.wide.setSizes([180, 400, 460])
        self.wide.setVisible(not narrow)
        self.tabs.setVisible(narrow)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def refresh_gallery(self):
        self.gallery.blockSignals(True)
        self.gallery.clear()
        for pack in self.store.list_packs():
            item = QListWidgetItem(pack.manifest['name'])
            entry = pack.entry_for('idle')
            item.setIcon(sprite_icon(pack.root / entry['asset'], entry.get('rect')))
            item.setToolTip('内置模板 · 先复制再编辑' if pack.builtin else '我的二创作品')
            item.setData(Qt.UserRole, pack.id)
            self.gallery.addItem(item)
            if pack.id == self.selected_id:
                self.gallery.setCurrentItem(item)
        self.gallery.blockSignals(False)

    def load_pack(self, pack_id):
        pack = self.store.load(pack_id)
        self.selected_id = pack.id
        self.gallery.blockSignals(True)
        for index in range(self.gallery.count()):
            item = self.gallery.item(index)
            if item.data(Qt.UserRole) == pack.id:
                self.gallery.setCurrentItem(item)
        self.gallery.blockSignals(False)
        self._load_draft(copy.deepcopy(pack.manifest),
                         {p.relative_to(pack.root).as_posix(): p for p in (pack.root / 'assets').rglob('*') if p.is_file()},
                         not pack.builtin)
        self.feedback.setText('内置模板 · 点击“复制当前作品”开始二创。' if pack.builtin else '作品已载入。保存后点击“应用到小伙伴”生效。')

    def _load_draft(self, draft, assets, editable):
        self._loading = True
        self.draft, self.assets, self.editable = draft, assets, editable
        self.name_edit.setText(draft['name'])
        self.author_edit.setText(draft['author'])
        self.desc_edit.setText(draft['description'])
        for widget in (self.name_edit, self.author_edit, self.desc_edit):
            widget.setReadOnly(not editable)
        self.editor.load(draft, editable)
        self.preview.set_draft(draft, assets)
        self._preview_current()
        self.dirty = False
        self._loading = False
        self._update_actions()

    def _update_actions(self):
        self.save_button.setEnabled(self.editable)
        self.discard_button.setEnabled(self.dirty)
        self.discard_button.setVisible(self.dirty)
        self.apply_button.setEnabled(not self.dirty)

    def _changed(self, *_):
        if self._loading or not self.editable:
            return
        self.draft.update(name=self.name_edit.text(), author=self.author_edit.text(), description=self.desc_edit.text())
        self.dirty = True
        self._update_actions()
        self._preview_current()
        self.feedback.setText('草稿有未保存修改 · 当前小伙伴仍使用已应用的作品。')

    def _preview_current(self):
        if self.draft:
            self.preview.show_entry(self.editor.current_entry())

    def copy_draft(self):
        self.editor.commit_current()
        data = copy.deepcopy(self.draft)
        data['id'] = 'copy'
        data['name'] = data['name'][:55] + ' · 二创'
        self._load_draft(data, dict(self.assets), True)
        self._changed()

    def new_draft(self):
        if not self._confirm_unsaved():
            return
        self.load_pack('starlight')
        self.copy_draft()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def discard_draft(self):
        self.load_pack(self.selected_id)

    def save_draft(self):
        if not self.editable:
            return None
        self.editor.commit_current()
        self.draft.update(name=self.name_edit.text().strip(), author=self.author_edit.text().strip(), description=self.desc_edit.text())
        try:
            # Copy only referenced sources; discarded replacements never bloat a pack.
            entries = list(self.draft['states'].values()) + self.draft['memes']
            assets = {entry['asset']: self.assets[entry['asset']] for entry in entries if entry['asset'] in self.assets}
            pack = self.store.save(self.draft, assets)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.feedback.setText(f'作品未保存：{exc}。草稿仍保留。')
            return None
        self.load_pack(pack.id)
        self.refresh_gallery()
        self.feedback.setText('作品已保存 · 点击“应用到小伙伴”使用这一版。')
        return pack

    def apply_pack(self):
        if self.dirty:
            self.feedback.setText('请先保存修改，再应用到小伙伴。')
            return
        try:
            self.controller.apply_pack(self.selected_id)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.feedback.setText(f'应用失败：{exc}')
            return
        self.feedback.setText(f'正在使用：{self.draft["name"]}。两种显示模式均已更新。')

    def choose_asset(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择表情或动图', '', '表情素材 (*.png *.webp *.gif)')
        if path:
            self.import_asset(Path(path))

    def import_asset(self, path):
        if not self.editable:
            return False
        path = Path(path)
        try:
            relative = 'assets/' + uuid.uuid4().hex + path.suffix.lower()
            safe_path(relative)
            image_size(path)
            target = Path(self._temp.name) / Path(relative).name
            shutil.copyfile(path, target)
        except (ValueError, OSError) as exc:
            self.feedback.setText(f'素材未替换：{exc}')
            return False
        self.assets[relative] = target
        entry = self.editor.current_entry()
        entry['asset'] = relative
        entry.pop('rect', None)
        entry['frame'] = 0
        self.editor.frame.setValue(0)
        self._changed()
        return True

    def import_pack(self):
        if not self._confirm_unsaved():
            return
        path, _ = QFileDialog.getOpenFileName(self, '导入二创作品包', '', '二创作品包 (*.zip)')
        if not path:
            return
        try:
            pack = self.store.import_zip(path)
            self.load_pack(pack.id)
            self.refresh_gallery()
            self.feedback.setText('作品已导入，原有作品保留。')
        except Exception as exc:
            self.feedback.setText(f'导入失败：{exc}')

    def export_pack(self):
        if self.dirty:
            self.feedback.setText('请先保存草稿，再导出作品。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出二创作品包', 'sariana-creation.zip', '二创作品包 (*.zip)')
        if path:
            try:
                self.store.export_zip(self.selected_id, path)
                self.feedback.setText(f'作品包已导出：{path}')
            except (ValueError, OSError) as exc:
                self.feedback.setText(f'导出失败：{exc}')

    def delete_pack(self):
        pack = self.store.load(self.selected_id)
        if pack.builtin:
            self.feedback.setText('内置模板始终保留；可删除自己保存的二创作品。')
            return
        if QMessageBox.question(self, '删除二创作品', f'删除“{pack.manifest["name"]}”？当前使用它时会回到星光陪伴。') != QMessageBox.Yes:
            return
        try:
            self.store.delete(pack.id)
            if self.controller.pack.id == pack.id:
                self.controller.apply_pack('starlight')
            self.load_pack('starlight')
            self.refresh_gallery()
            self.feedback.setText('作品已从列表移除。')
        except (ValueError, OSError) as exc:
            self.feedback.setText(f'删除失败：{exc}')

    def _selection_changed(self, item, previous):
        if not item:
            return
        requested_id = item.data(Qt.UserRole)
        if self._confirm_unsaved():
            self.load_pack(requested_id)
        elif previous:
            self.gallery.blockSignals(True)
            self.gallery.setCurrentItem(previous)
            self.gallery.blockSignals(False)

    def _confirm_unsaved(self):
        if not self.dirty:
            return True
        result = QMessageBox.question(self, '保留创作草稿', '有未保存的修改。保存作品后再继续？',
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                                      QMessageBox.Save)
        if result == QMessageBox.Save:
            return self.save_draft() is not None
        return result == QMessageBox.Discard

    def reject(self):
        if self._confirm_unsaved():
            self.discard_draft()
            super().reject()

    def closeEvent(self, event):
        if self._confirm_unsaved():
            self.discard_draft()
            event.accept()
        else:
            event.ignore()
