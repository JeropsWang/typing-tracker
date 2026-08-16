"""主题插件系统（M4）：内置主题 + 用户导入主题。

主题包结构（文件夹或 .zip，一键导入到数据目录 themes/）：
  manifest.json   元数据：{id, name, version, author, base, colors{...}, fonts{...}}
  theme.qss       Qt 样式表，支持 {{colors.primary}} / {{fonts.family}} 占位符
  charts.json     图表配色：{background, grid, speed, acc, chars, levels[], empty}
  assets/         （可选）图片素材

ThemeManager 职责：扫描注册 → 校验导入 → 变量替换 → 应用 QSS 与图表配色 →
实时预览（切换即应用）→ 删除用户主题 / 还原默认。
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

BUILTIN_DIR = Path(__file__).parent / 'themes'
VAR_RE = re.compile(r'\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}')


class ThemeManager:
    def __init__(self, app, data_dir, get_setting, set_setting):
        self._app = app
        self._user_dir = Path(data_dir) / 'themes'
        self._user_dir.mkdir(parents=True, exist_ok=True)
        self._get_setting = get_setting
        self._set_setting = set_setting
        self._reports = None
        self._window = None
        self._registry = self._scan()

    # ---------- 扫描注册 ----------
    def _scan(self) -> dict:
        reg = {}
        for root in (BUILTIN_DIR, self._user_dir):
            if not root.exists():
                continue
            for d in root.iterdir():
                mf = d / 'manifest.json'
                if d.is_dir() and mf.exists():
                    try:
                        m = json.loads(mf.read_text(encoding='utf-8'))
                        if m.get('id') and m.get('name'):
                            m['_dir'] = str(d)
                            m['_builtin'] = (root == BUILTIN_DIR)
                            reg[m['id']] = m
                    except (ValueError, OSError):
                        continue
        return reg

    def list_themes(self) -> list:
        return sorted(self._registry.values(),
                      key=lambda m: (not m['_builtin'], m['id']))

    def get(self, theme_id):
        return self._registry.get(theme_id)

    def current_id(self) -> str:
        tid = self._get_setting('theme_id', '')
        return tid if tid in self._registry else 'default_light'

    # ---------- 应用 ----------
    def apply(self, theme_id) -> None:
        m = self._registry.get(theme_id)
        if not m:
            return
        qss = self._render_qss(Path(m['_dir']) / 'theme.qss', m)
        # 下拉箭头（QSS 不支持 data URI，程序生成 PNG 到数据目录）
        arrow = self._ensure_arrow(m.get('base') != 'light')
        if arrow:
            qss = qss.replace('{{arrow}}', arrow.as_posix())
        effects = m.get('effects') or {}
        # 全局调色板：所有页面文字/卡片颜色随主题（可读性）
        try:
            from ..ui.palette import P
            P.update(m.get('colors') or {}, effects)
        except Exception:
            pass
        # 星空背景模式下仅面板容器透明（页面控件背景由主题 QSS 各自控制）
        if effects.get('background') == 'stars':
            qss += '\n#mainTabs::pane { background: transparent; border: none; }'
        self._app.setStyleSheet(qss or '')
        charts = self._load_charts(Path(m['_dir']) / 'charts.json')
        if self._reports is not None and charts:
            self._reports.apply_chart_palette(charts)
        if self._window is not None:
            self._window.apply_effects(effects)
            shell_bg = m.get('shell_bg')
            if shell_bg:
                self._window.apply_shell_style(shell_bg)
        self._set_setting('theme_id', theme_id)

    def register_reports(self, reports) -> None:
        """注册报表页，应用当前主题的图表配色。"""
        self._reports = reports
        m = self._registry.get(self.current_id())
        if m:
            charts = self._load_charts(Path(m['_dir']) / 'charts.json')
            if charts:
                reports.apply_chart_palette(charts)

    def register_window(self, window) -> None:
        """注册主窗口，应用当前主题的动态效果（星空/光效/配色）。"""
        self._window = window
        m = self._registry.get(self.current_id())
        if m:
            try:
                from ..ui.palette import P
                P.update(m.get('colors') or {}, m.get('effects') or {})
            except Exception:
                pass
            window.apply_effects(m.get('effects') or {})
            shell_bg = m.get('shell_bg')
            if shell_bg:
                window.apply_shell_style(shell_bg)

    def _render_qss(self, path: Path, manifest: dict) -> str:
        if not path.exists():
            return ''
        text = path.read_text(encoding='utf-8')

        def repl(mo):
            node = manifest
            for part in mo.group(1).split('.'):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    return ''
            return str(node)

        return VAR_RE.sub(repl, text)

    def _ensure_arrow(self, light_on_dark: bool):
        """生成 QComboBox 下拉箭头 PNG（深色主题用浅箭头，反之亦然）。"""
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QColor, QImage, QPainter, QPolygonF, QPointF
            name = '__arrow_light.png' if light_on_dark else '__arrow_dark.png'
            path = self._user_dir / name
            if path.exists():
                return path
            img = QImage(14, 14, QImage.Format_ARGB32)
            img.fill(Qt.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#E2E8F0' if light_on_dark else '#4B5563'))
            p.drawPolygon(QPolygonF([
                QPointF(2.0, 4.5), QPointF(12.0, 4.5), QPointF(7.0, 11.0)]))
            p.end()
            img.save(str(path))
            return path
        except Exception:
            return None

    @staticmethod
    def _load_charts(path: Path):
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except ValueError:
            return None

    # ---------- 导入 / 删除 ----------
    def import_theme(self, zip_path) -> tuple:
        """导入 .zip 主题包；返回 (成功, 消息)。"""
        try:
            with zipfile.ZipFile(zip_path) as z:
                names = z.namelist()
                mf = next((n for n in names if n.endswith('manifest.json')), None)
                if not mf:
                    return False, '主题包缺少 manifest.json'
                root = mf.rsplit('/', 1)[0] if '/' in mf else ''
                manifest = json.loads(z.read(mf))
                tid = manifest.get('id')
                if not tid or not manifest.get('name'):
                    return False, 'manifest.json 缺少 id / name 字段'
                if tid in self._registry and self._registry[tid]['_builtin']:
                    return False, f'主题 id 与内置主题冲突：{tid}'
                if not any(n.endswith('.qss') for n in names):
                    return False, '主题包缺少 .qss 样式文件'
                target = self._user_dir / tid
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                target.mkdir(parents=True)
                for n in names:
                    if n.endswith('/'):
                        continue
                    rel = n[len(root):].lstrip('/')
                    if not rel:
                        continue
                    dest = target / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(n))
                self._registry = self._scan()
                return True, f'已导入主题「{manifest["name"]}」'
        except (json.JSONDecodeError, zipfile.BadZipFile, OSError) as e:
            return False, f'导入失败：{e}'

    def delete_theme(self, theme_id) -> tuple:
        m = self._registry.get(theme_id)
        if not m:
            return False, '主题不存在'
        if m['_builtin']:
            return False, '内置主题不可删除'
        shutil.rmtree(m['_dir'], ignore_errors=True)
        self._registry = self._scan()
        return True, f'已删除主题「{m["name"]}」'
