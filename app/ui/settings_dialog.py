"""设置对话框：个人信息 / 单位 / 日切 / 无限等级 / 排除程序 / AI 配置 / 主题 / 导出。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QVBoxLayout,
)

from ..services.export_service import export_all
from .palette import P

_AI_BACKENDS = [('off', '关闭'), ('openai', 'OpenAI 兼容（API Key）'),
                ('ollama', 'Ollama 本地（无需 Key）')]
_AI_PLACEHOLDERS = {
    'openai': ('https://api.openai.com/v1', 'sk-...（支持 DeepSeek/智谱等兼容服务）'),
    'ollama': ('http://127.0.0.1:11434/v1', '本地服务无需 Key，可留空'),
}


class SettingsDialog(QDialog):
    def __init__(self, repo, balance, parent=None, theme_manager=None):
        super().__init__(parent)
        self.setWindowTitle('设置')
        self._repo = repo
        self._balance = balance
        self._theme_mgr = theme_manager

        form = QFormLayout()

        # 个人信息（个人中心展示）
        self._nick_edit = QLineEdit(repo.get_setting('nickname', '打字新星'))
        self._nick_edit.setMaxLength(12)
        form.addRow('昵称', self._nick_edit)
        self._sig_edit = QLineEdit(repo.get_setting('signature', '键盘上的舞者 ✨'))
        self._sig_edit.setMaxLength(30)
        form.addRow('签名', self._sig_edit)
        self._avatar_combo = QComboBox()
        for emoji in ['🐱', '🐰', '🐻', '🦊', '🐼', '🐨', '🐹', '🐯', '🐸', '🐵', '🐶', '🦄']:
            self._avatar_combo.addItem(emoji)
        cur = repo.get_setting('avatar_emoji', '🐱')
        idx = self._avatar_combo.findText(cur)
        self._avatar_combo.setCurrentIndex(max(0, idx))
        form.addRow('头像', self._avatar_combo)

        self._unit_edit = QLineEdit(repo.get_setting('unit_name', balance['unit']['name']))
        self._unit_edit.setPlaceholderText('如 tw / 字')
        form.addRow('单位名称', self._unit_edit)

        self._hour_spin = QSpinBox()
        self._hour_spin.setRange(0, 23)
        self._hour_spin.setValue(int(repo.get_setting('day_start_hour', balance['day_start_hour'])))
        form.addRow('新的一天从几点开始', self._hour_spin)

        self._infinite = QCheckBox('开启无限等级之路（100 级后继续按公式累加，无上限）')
        self._infinite.setChecked(repo.get_setting('infinite_levels', '0') == '1')
        form.addRow('', self._infinite)

        self._exclude_edit = QPlainTextEdit(repo.get_setting('excluded_apps', ''))
        self._exclude_edit.setPlaceholderText('每行一个程序名（如 PasswordManager.exe）')
        form.addRow('排除统计的程序', self._exclude_edit)

        # AI 配置（竞速挑战范文生成）
        self._ai_backend = QComboBox()
        for val, name in _AI_BACKENDS:
            self._ai_backend.addItem(name, val)
        cur_backend = repo.get_setting('ai_backend', 'off')
        idx = self._ai_backend.findData(cur_backend)
        self._ai_backend.setCurrentIndex(max(0, idx))
        self._ai_backend.currentIndexChanged.connect(self._ai_placeholder)
        form.addRow('AI 后端', self._ai_backend)
        self._ai_url = QLineEdit(repo.get_setting('ai_base_url', ''))
        form.addRow('Base URL', self._ai_url)
        self._ai_key = QLineEdit(repo.get_setting('ai_api_key', ''))
        self._ai_key.setEchoMode(QLineEdit.Password)
        form.addRow('API Key', self._ai_key)
        self._ai_model = QLineEdit(repo.get_setting('ai_model', ''))
        form.addRow('模型', self._ai_model)
        ai_row = QHBoxLayout()
        btn_test = QPushButton('测试连接')
        btn_test.clicked.connect(self._ai_test)
        ai_row.addWidget(btn_test)
        self._ai_result = QLabel('')
        self._ai_result.setWordWrap(True)
        ai_row.addWidget(self._ai_result, 1)
        form.addRow('', ai_row)
        self._ai_placeholder()

        if theme_manager is not None:
            theme_row = QHBoxLayout()
            self._theme_combo = QComboBox()
            self._theme_combo.currentIndexChanged.connect(self._apply_theme)
            theme_row.addWidget(self._theme_combo, 1)
            btn_import = QPushButton('导入主题…')
            btn_import.clicked.connect(self._import_theme)
            theme_row.addWidget(btn_import)
            btn_delete = QPushButton('删除')
            btn_delete.clicked.connect(self._delete_theme)
            theme_row.addWidget(btn_delete)
            form.addRow('主题插件', theme_row)
            self._reload_themes()

            exp_row = QHBoxLayout()
            btn_export = QPushButton('导出数据备份…')
            btn_export.clicked.connect(self._export)
            exp_row.addWidget(btn_export)
            form.addRow('数据', exp_row)

        hint = QLabel('说明：1 字母 = 1tw、1 汉字 = 2tw；平均速度与正确率按日统计，不并入终身总计。')
        hint.setWordWrap(True)
        hint.setStyleSheet(f'color:{P.muted};')

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(btns)

    # ---------- AI ----------
    def _ai_placeholder(self):
        backend = self._ai_backend.currentData()
        url_hint, key_hint = _AI_PLACEHOLDERS.get(backend, ('', ''))
        self._ai_url.setPlaceholderText(url_hint)
        self._ai_key.setPlaceholderText(key_hint)

    def _ai_test(self):
        from ..services.ai_service import AIService
        self._save_ai()
        svc = AIService(self._repo)
        ok, msg = svc.test_connection()
        self._ai_result.setText(msg)
        self._ai_result.setStyleSheet(
            f'color:{"#10b981" if ok else "#ef4444"}; font-size:11px;')

    def _save_ai(self):
        self._repo.set_setting('ai_backend', self._ai_backend.currentData())
        self._repo.set_setting('ai_base_url', self._ai_url.text().strip())
        self._repo.set_setting('ai_api_key', self._ai_key.text().strip())
        self._repo.set_setting('ai_model', self._ai_model.text().strip())

    # ---------- 主题 ----------
    def _reload_themes(self):
        self._theme_combo.blockSignals(True)
        self._theme_combo.clear()
        current = self._theme_mgr.current_id()
        idx = 0
        for i, m in enumerate(self._theme_mgr.list_themes()):
            self._theme_combo.addItem(
                f'{m["name"]}（内置）' if m['_builtin'] else f'{m["name"]}（用户）',
                m['id'])
            if m['id'] == current:
                idx = i
        self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.blockSignals(False)

    def _apply_theme(self, *_):
        tid = self._theme_combo.currentData()
        if tid:
            self._theme_mgr.apply(tid)

    def _import_theme(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择主题包', '', '主题包 (*.zip)')
        if not path:
            return
        ok, msg = self._theme_mgr.import_theme(path)
        QMessageBox.information(self, '导入主题', msg)
        if ok:
            self._reload_themes()

    def _delete_theme(self):
        tid = self._theme_combo.currentData()
        if not tid:
            return
        ok, msg = self._theme_mgr.delete_theme(tid)
        QMessageBox.information(self, '删除主题', msg)
        if ok:
            self._reload_themes()

    def _export(self):
        out_dir = QFileDialog.getExistingDirectory(self, '选择导出目录')
        if not out_dir:
            return
        try:
            folder = export_all(self._repo, out_dir)
            QMessageBox.information(
                self, '导出完成', f'备份已保存到：\n{folder}\n'
                '（daily_stats.csv + data.json）')
        except OSError as e:
            QMessageBox.warning(self, '导出失败', str(e))

    def accept(self):
        self._repo.set_setting('nickname', self._nick_edit.text().strip() or '打字新星')
        self._repo.set_setting('signature', self._sig_edit.text().strip() or '键盘上的舞者 ✨')
        self._repo.set_setting('avatar_emoji', self._avatar_combo.currentText())
        self._repo.set_setting('unit_name', self._unit_edit.text().strip() or 'tw')
        self._save_ai()
        self._repo.set_setting('day_start_hour', str(self._hour_spin.value()))
        self._repo.set_setting('infinite_levels', '1' if self._infinite.isChecked() else '0')
        self._repo.set_setting('excluded_apps', self._exclude_edit.toPlainText())
        super().accept()
