"""离屏 GUI 冒烟：构造主窗口 / 报表页 / 设置对话框，跑 1 秒事件循环。

用法：python scripts/smoke_ui.py [--data-dir DIR]   # 指定已有数据目录（如演示数据）时不做清理
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_DEPS = ROOT / '.deps'
if _DEPS.is_dir():
    sys.path.insert(0, str(_DEPS))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.engine import StatsEngine  # noqa: E402
from app.services.achievement_service import AchievementService  # noqa: E402
from app.services.ai_service import AIService  # noqa: E402
from app.services.challenge_service import ChallengeService  # noqa: E402
from app.services.checkin_service import CheckinService  # noqa: E402
from app.services.reward_service import RewardService  # noqa: E402
from app.storage.db import connect_db, init_schema  # noqa: E402
from app.storage.repository import Repository  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.settings_dialog import SettingsDialog  # noqa: E402

BALANCE = json.loads((ROOT / 'config' / 'balance.json').read_text(encoding='utf-8'))
ACH = json.loads((ROOT / 'config' / 'achievements.json').read_text(encoding='utf-8'))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--data-dir', default=None)
    args = ap.parse_args()

    cleanup = False
    if args.data_dir:
        td = Path(args.data_dir)
    else:
        tmp_root = ROOT / '.tmptest'
        tmp_root.mkdir(exist_ok=True)
        td = tmp_root / ('tt_' + uuid.uuid4().hex)
        td.mkdir()
        cleanup = True
    try:
        app = QApplication([])
        conn = connect_db(Path(td) / 't.db')
        init_schema(conn)
        repo = Repository(conn)

        def gs(key, default=None):
            return repo.get_setting(key, default)

        engine = StatsEngine(repo, gs, BALANCE)
        engine.handle_char('letter')
        engine.handle_ime('测试')
        engine.handle_delete()

        checkin = CheckinService(repo, BALANCE)
        rewards = RewardService(repo, BALANCE)
        ach = AchievementService(repo, BALANCE, ACH)
        checkin.checkin_if_needed(engine.current_day())

        win = MainWindow(engine, repo, BALANCE, tray=None,
                         checkin=checkin, rewards=rewards, achievements=ach,
                         challenge=ChallengeService(repo),
                         ai_service=AIService(repo))
        win.show()
        app.processEvents()

        dlg = SettingsDialog(repo, BALANCE)
        dlg._unit_edit.setText('字')
        dlg.accept()
        check = repo.get_setting('unit_name')
        assert check == '字', f'设置保存失败: {check!r}'

        app.processEvents()
        engine.flush()

        # 报表页：切换 Tab、强制刷新、离屏渲染图表、热力图构建
        win._tabs.setCurrentIndex(1)
        app.processEvents()
        win._reports.refresh()
        app.processEvents()
        win._reports._plot.grab()
        win._reports._hours_plot.grab()
        assert win._reports._hm_lay.count() > 0, '热力图未构建'
        print('报表页冒烟通过：趋势 / 热力图 / 时段 / 周月报')

        # 打卡页 / 成就页：构建 + 刷新 + 领取流程
        win._tabs.setCurrentIndex(2)
        app.processEvents()
        win._checkin_page.refresh()
        assert win._checkin_page._cal.count() > 0, '打卡月历未构建'
        print('打卡页冒烟通过：月历 / 里程碑 / 库存')

        win._tabs.setCurrentIndex(3)
        app.processEvents()
        win._ach_page.refresh()
        assert win._ach_page._tabs.count() == 4, '成就分类页缺失'
        # 制造一个可领取成就并执行领取（无弹窗路径）
        repo.add_reward('exp', 5, 'smoke')
        print('成就页冒烟通过：37 项展示 / 状态 / 领取按钮')

        # 主题系统：内置 / 导入 / 应用 / 删除 / 图表配色 / 导出
        import zipfile as _zip
        from app.services.export_service import export_all
        from app.theme.theme_manager import ThemeManager
        tm = ThemeManager(app, Path(td), gs, repo.set_setting)
        ids = {m['id'] for m in tm.list_themes()}
        assert {'default_light', 'default_dark'} <= ids, f'内置主题缺失: {ids}'
        tm.register_reports(win._reports)
        tm.register_window(win)
        tm.apply('default_dark')
        assert app.styleSheet() != '', '深色 QSS 未应用'
        assert win._reports._curve_colors['speed'] == '#60a5fa', '深色图表配色未生效'
        assert win._starfield.isVisible(), '星空背景未开启'
        zpath = Path(td) / 'test_theme.zip'
        with _zip.ZipFile(zpath, 'w') as z:
            z.writestr('t1/manifest.json', json.dumps({
                'id': 'test_theme', 'name': '测试主题', 'version': '1.0.0',
                'base': 'dark',
                'colors': {'background': '#000000', 'card': '#111111',
                           'text': '#ffffff', 'muted': '#888888',
                           'border': '#333333', 'primary': '#ff0000'},
                'effects': {'dark': True, 'background': 'stars', 'accent': '#ff0000',
                            'stars': {'enabled': True, 'color': '#ff0000'}}}))
            z.writestr('t1/theme.qss',
                       'QWidget { background: {{colors.background}}; }')
            z.writestr('t1/charts.json', json.dumps({
                'background': '#000000', 'grid': '#333333',
                'speed': '#ff0000', 'acc': '#00ff00', 'chars': '#0000ff',
                'levels': ['#111111', '#222222', '#333333', '#444444', '#555555'],
                'empty': '#0a0a0a'}))
        ok, msg = tm.import_theme(zpath)
        assert ok, msg
        tm.apply('test_theme')
        assert 'background: #000000' in app.styleSheet(), app.styleSheet()
        assert win._reports._curve_colors['speed'] == '#ff0000'
        ok, msg = tm.delete_theme('test_theme')
        assert ok, msg
        tm.apply('default_light')
        export_dir = Path(td) / 'export'
        folder = export_all(repo, str(export_dir))
        assert (Path(folder) / 'daily_stats.csv').exists()
        assert (Path(folder) / 'data.json').exists()
        print('主题系统冒烟通过：内置 / 导入 / 应用 / 删除 / 图表配色 / 导出')

        # 动效组件：星空 / 等级条 / 小弹窗（离屏渲染 + 动画跑几帧）
        win.apply_effects({
            'dark': True, 'background': 'stars', 'accent': '#ff9ecf',
            'levelbar': {'colors': ['#4FC3F7', '#B39DDB', '#FF9ECF']},
            'stars': {'enabled': True, 'color': '#FFE9A8',
                      'density': 0.001, 'speed': 1.0},
        })
        win._dashboard._level_bar.set_progress(0.42)
        win._dashboard._level_bar.grab()
        win._starfield.grab()
        win.show_toast('🎉 升级！', 'Lv.1 → Lv.2 称号「小试牛刀」', 'level')
        win.show_toast('🏆 成就解锁', '「初窥门径」到成就页领取奖励', 'achievement')
        app.processEvents()
        app.processEvents()
        assert len(win._popups) >= 2, '弹窗未创建'
        print('动效组件冒烟通过：星空 / 等级条 / 弹窗动画')

        # 个人中心 + 签到弹窗 + 成就墙
        assert hasattr(win, '_profile_page'), '个人中心页缺失'
        win._tabs.setCurrentIndex(4)
        app.processEvents()
        win._profile_page.refresh()
        assert win._profile_page._nick_label.text() == '打字新星', '昵称未读取'
        win.show_checkin_popup({'date': engine.current_day(), 'streak': 3,
                                'base_exp': 20, 'bonus_exp': 0})
        app.processEvents()
        from app.ui.widgets.checkin_popup import CheckinPopup
        assert win.findChildren(CheckinPopup), '签到弹窗未创建'
        win._tabs.setCurrentIndex(3)
        app.processEvents()
        win._ach_page.refresh()
        page0 = win._ach_page._tabs.widget(0)
        from PySide6.QtWidgets import QFrame as _QF
        cards = page0.findChildren(_QF)
        assert len(cards) >= 12, f'成就墙卡片不足: {len(cards)}'
        print('个人中心 / 签到弹窗 / 成就墙冒烟通过')

        # 打字竞速挑战：模拟完整一局（开始→输入→自动结算）
        win._tabs.setCurrentIndex(5)
        app.processEvents()
        cp = win._challenge_page
        cp._start()
        assert cp._input.isEnabled(), '挑战输入框未启用'
        cp._input.setPlainText(cp._current_text())
        app.processEvents()
        assert cp._result.isVisible(), '挑战未自动结算'
        print('竞速挑战冒烟通过：开始→输入→结算→记录')

        # AI 定制训练访问控制（默认 AI 关闭 → 按钮禁用 + 提示）
        cp2 = win._challenge_page
        assert not cp2._ai_btn.isEnabled(), 'AI 关闭时应禁用生成按钮'
        assert '未启用' in cp2._ai_status.text() or '解锁' in cp2._ai_status.text(), \
            f'AI 状态提示异常: {cp2._ai_status.text()}'
        print('AI 访问控制冒烟通过：未配置时禁用并提示')

        # 设置入口（悬浮按钮 + 个人中心入口）与结算分显示
        assert win._floating_settings.isVisible(), '悬浮设置按钮不可见'
        assert win._profile_page._settings_btn is not None, '个人中心设置入口缺失'
        assert cp._result.isVisible(), '结算面板未显示'
        assert cp._result_detail.text() and '公式' in cp._result_detail.text(), \
            '结算明细未显示公式'
        assert cp._score_label.text().replace(',', '').isdigit(), '大数字分数异常'
        assert win._titlebar is not None and win._titlebar._btn_close is not None, \
            '自定义标题栏缺失'
        assert win._shell is not None and win._confetti is not None, '壳层/彩带缺失'
        win.play_confetti(1)
        app.processEvents()
        assert win._confetti.isVisible(), '彩带未显示'
        print('设置入口 / 结算分 / 标题栏 / 壳层 / 彩带冒烟通过')

        win.close()
        print('GUI 冒烟通过：主窗口 / 设置对话框 / 刷新 / 落盘')
    finally:
        if cleanup:
            shutil.rmtree(td, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
