"""界面预览与截图：使用隔离数据库，不安装键盘钩子、不修改用户记录。

python scripts/preview_ui.py                 # 默认主题（梨诺）、三种尺寸截图与布局体检
python scripts/preview_ui.py --interactive   # 可交互预览，关闭窗口退出
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--out', default='.local/ui-night-stage/previews',
                        help='截图输出目录（并行验工时用各自目录，避免互相覆盖）')
    parser.add_argument('--only', default='',
                        help='只渲染指定页面，逗号分隔：today,training,stats,checkin,achievements,profile')
    parser.add_argument('--themes', default='arknights_endfield_lino',
                        help='逗号分隔的主题 id（默认只有唯一内置主题梨诺；'
                             '也可填数据目录 themes/ 下导入的第三方主题）')
    parser.add_argument('--sizes', default='1440x1024', help='主窗口固定 1440×1024，尺寸请求不改变窗口')
    parser.add_argument('--no-shell', action='store_true',
                        help='不构造主窗口，只渲染设置对话框（其它页面在途改动时独立验证）')
    parser.add_argument('--expanded-ai', action='store_true', help='截图训练页展开的 AI 范文表单')
    parser.add_argument('--expanded-records', action='store_true', help='截图训练页展开的个人练习榜')
    args = parser.parse_args()
    if not args.interactive:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from ui_test_support import prepare_fonts, load_fonts
    prepare_fonts()

    from PySide6.QtWidgets import QApplication
    from app.core.engine import StatsEngine
    from app.services.achievement_service import AchievementService
    from app.services.ai_service import AIService
    from app.services.challenge_service import ChallengeService
    from app.services.checkin_service import CheckinService
    from app.services.reward_service import RewardService
    from app.storage.db import connect_db, init_schema
    from app.storage.repository import Repository
    from app.theme.theme_manager import ThemeManager
    from app.ui.main_window import MainWindow
    from app.ui.settings_dialog import SettingsDialog
    if not args.interactive:
        from layout_audit import audit_window

    app = QApplication([])
    load_fonts()
    output = ROOT / args.out
    output.mkdir(parents=True, exist_ok=True)
    data = ROOT / '.local/ui-night-stage/preview-data'
    data.mkdir(parents=True, exist_ok=True)
    # 每次截图使用全新内存库；交互预览保留自己的设置与练习记录。
    conn = connect_db(data / 'preview.db' if args.interactive else ':memory:')
    init_schema(conn)
    repo = Repository(conn)
    balance = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
    definitions = json.loads((ROOT / 'config/achievements.json').read_text(encoding='utf-8'))
    theme = ThemeManager(app, data, repo.get_setting, repo.set_setting)

    class PreviewWindow(MainWindow):
        def closeEvent(self, event):
            event.accept()
            app.quit()

    only = {name.strip() for name in args.only.split(',') if name.strip()}
    # 主题列表：已不存在的主题名给出清晰提示并跳过，不崩溃。
    themes = [name.strip() for name in args.themes.split(',') if name.strip()]
    known = {m['id'] for m in theme.list_themes()}
    missing = [name for name in themes if name not in known]
    for name in missing:
        print(f'跳过主题「{name}」：主题不存在（可用：{", ".join(sorted(known)) or "无"}）',
              file=sys.stderr)
    themes = [name for name in themes if name in known]
    if not themes:
        raise SystemExit(f'没有可用主题，已请求：{", ".join(missing) or "（空）"}；'
                         f'可用主题：{", ".join(sorted(known)) or "无"}')
    # --no-shell：只渲染设置对话框，不构造主窗口（其它页面在途改动时也能独立验证）
    window = None
    if not args.no_shell:
        window = PreviewWindow(StatsEngine(repo, repo.get_setting, balance), repo, balance,
                               checkin=CheckinService(repo, balance), rewards=RewardService(repo, balance),
                               achievements=AchievementService(repo, balance, definitions),
                               challenge=ChallengeService(repo), ai_service=AIService(repo),
                               theme_manager=theme, data_dir=data)
        theme.register_reports(window._reports)
        theme.register_window(window)
        # 非交互截图固定用请求的第一个主题，避免残留的 theme_id 影响底稿。
        theme.apply(theme.current_id() if args.interactive else themes[0])
        window._dashboard._hook_status.setText('界面预览 · 未启动后台统计')
        window._dashboard._hook_info.setText('预览数据独立保存，不影响日常打字记录。')
        window.show()
        window.refresh()
        app.processEvents()
        if args.interactive:
            window.raise_()
            window.activateWindow()
            print(f'Preview ready: platform={app.platformName()}, visible={window.isVisible()}', flush=True)
            result = app.exec()
            conn.close()
            return result
    else:
        theme.apply(themes[0])

    issues = []
    pages = [] if window is None else [
        ('today', window._dashboard), ('training', window._challenge_page),
        ('stats', window._reports), ('checkin', window._checkin_page),
        ('achievements', window._ach_page), ('profile', window._profile_page)]
    if only:
        pages = [item for item in pages if item[0] in only]
    sizes = []
    for chunk in args.sizes.split(','):
        if 'x' in chunk:
            width, height = chunk.split('x')
            sizes.append((int(width), int(height)))
    for theme_id in themes:
        theme.apply(theme_id)
        for width, height in sizes:
            if window is None:
                break
            window.resize(width, height)
            for label, page in pages:
                window._tabs.setCurrentWidget(page)
                if label == 'training' and args.expanded_ai:
                    page._ai_section.toggle.setChecked(True)
                if label == 'training' and args.expanded_records:
                    page._recent_disclosure.toggle.setChecked(True)
                for _ in range(8):
                    app.processEvents()
                if label == 'training' and args.expanded_ai:
                    page._page_scroll.ensureWidgetVisible(page._ai_composer, 0, 0)
                    app.processEvents()
                if label == 'training' and args.expanded_records:
                    page._page_scroll.ensureWidgetVisible(page._secondary, 0, 0)
                    app.processEvents()
                tag = f'{theme_id}-{window.width()}-{label}'
                window.grab().save(str(output / (tag + '.png')))
                issues.extend(audit_window(window, tag))
        if only and 'settings' not in only:
            continue
        settings = SettingsDialog(repo, balance, window, theme_manager=theme, data_dir=data)
        settings.show()
        for index, label in enumerate(('profile', 'rules', 'exclusion', 'ai', 'appearance', 'data')):
            settings._sections.setCurrentRow(index)
            if label == 'ai':
                settings._ai_backend.setCurrentIndex(1)
            app.processEvents()
            tag = f'{theme_id}-settings-{label}'
            settings.grab().save(str(output / (tag + '.png')))
            issues.extend(audit_window(settings, tag))
        settings.reject()
        settings.deleteLater()
        app.processEvents()
    for issue in issues:
        print(issue)
    (output / 'layout-report.json').write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'截图目录：{output}\n布局问题：{len(issues)}')
    if window is not None:
        window.hide()
    conn.close()
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
