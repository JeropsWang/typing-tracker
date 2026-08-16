"""打字管家 - 入口：单实例锁、初始化、后台钩子、托盘、主窗口。

用法：python main.py [--data-dir DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 本地依赖目录（.deps，沙箱环境下安装 PySide6 用），存在则优先加载
_DEPS = Path(__file__).resolve().parent / '.deps'
if _DEPS.is_dir():
    sys.path.insert(0, str(_DEPS))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from app import __version__
from app.core.engine import StatsEngine
from app.services.achievement_service import AchievementService
from app.services.ai_service import AIService
from app.services.challenge_service import ChallengeService
from app.services.checkin_service import CheckinService
from app.services.encourage_service import EncourageService
from app.services.reward_service import RewardService
from app.storage.db import connect_db, init_schema
from app.storage.repository import Repository
from app.theme.theme_manager import ThemeManager
from app.ui.main_window import MainWindow
from app.ui.tray import TrayIcon

try:
    from app.core.keyboard_hook import KeyboardHook
except Exception:  # 非 Windows 平台降级：无钩子，仅界面可用
    KeyboardHook = None

APP_NAME = '打字管家'
DEFAULT_DATA_DIR = Path.home() / 'AppData' / 'Roaming' / 'TypingTracker'


def load_balance() -> dict:
    p = Path(__file__).resolve().parent / 'config' / 'balance.json'
    return json.loads(p.read_text(encoding='utf-8'))


def load_achievements() -> dict:
    p = Path(__file__).resolve().parent / 'config' / 'achievements.json'
    return json.loads(p.read_text(encoding='utf-8'))


def ensure_default_settings(repo, balance) -> None:
    defaults = {
        'unit_name': balance['unit']['name'],
        'day_start_hour': str(balance['day_start_hour']),
        'infinite_levels': '0',
        'excluded_apps': '',
        'nickname': '打字新星',
        'signature': '键盘上的舞者 ✨',
        'avatar_emoji': '🐱',
        'active_title': '',
        'ai_backend': 'off',
        'ai_base_url': '',
        'ai_api_key': '',
        'ai_model': '',
    }
    for k, v in defaults.items():
        if repo.get_setting(k) is None:
            repo.set_setting(k, v)


def main() -> int:
    parser = argparse.ArgumentParser(prog='typing-tracker')
    parser.add_argument('--data-dir', default=str(DEFAULT_DATA_DIR),
                        help='数据目录（默认 %APPDATA%/TypingTracker）')
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # 关窗不退出，驻留托盘

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # 单实例锁（防双开重复计数）
    from PySide6.QtCore import QLockFile
    lock = QLockFile(str(data_dir / 'app.lock'))
    if not lock.tryLock(100):
        QMessageBox.warning(None, APP_NAME, '打字管家已在运行（单实例），请勿重复启动。')
        return 1

    balance = load_balance()
    ach_defs = load_achievements()
    conn = connect_db(data_dir / 'app.db')
    init_schema(conn)
    repo = Repository(conn)
    ensure_default_settings(repo, balance)

    def get_setting(key, default=None):
        return repo.get_setting(key, default)

    engine = StatsEngine(repo, get_setting, balance)
    checkin = CheckinService(repo, balance)
    achievements = AchievementService(repo, balance, ach_defs)
    encourage = EncourageService(repo, balance)
    rewards = RewardService(repo, balance)

    def notify(title: str, msg: str):
        print(f'[{title}] {msg}')

    # 每天首次启动自动打卡
    checkin_result = checkin.checkin_if_needed(engine.current_day())
    if checkin_result:
        notify('打卡',
               f'{checkin_result["date"]} 连签 {checkin_result["streak"]} 天，'
               f'+{checkin_result["total_exp"]} exp')
        if checkin_result.get('milestone'):
            notify('里程碑',
                   f'连签 {checkin_result["milestone"]} 天达成，里程碑礼包已发放！')
    startup_unlocks = achievements.check_all(engine)
    for a in startup_unlocks:
        notify('成就', f'解锁「{a["name"]}」，到成就页领取奖励')

    tray = TrayIcon()
    tray.show()
    window = MainWindow(engine, repo, balance, tray,
                        checkin=checkin, rewards=rewards,
                        achievements=achievements,
                        theme_manager=ThemeManager(
                            app, data_dir, get_setting, repo.set_setting),
                        challenge=ChallengeService(repo),
                        ai_service=AIService(repo),
                        data_dir=data_dir)
    theme_manager = window._theme_mgr
    theme_manager.register_reports(window._reports)
    theme_manager.register_window(window)
    theme_manager.apply(theme_manager.current_id())
    tray.show_requested.connect(window.show_and_raise)
    tray.settings_requested.connect(window.open_settings)
    tray.quit_requested.connect(app.quit)

    def toast(title: str, msg: str, kind: str = 'star'):
        print(f'[{title}] {msg}')
        window.notify(title, msg, kind)
        tray.showMessage(title, msg, QSystemTrayIcon.Information, 4000)

    # 打卡弹窗在窗口就绪后再弹（曾用 QTimer.singleShot 引用未定义变量）
    if checkin_result:
        QTimer.singleShot(800,
                          lambda r=checkin_result: window.show_checkin_popup(r))

    # 键盘钩子：尽早启动；失败时给用户明确可见的提示
    # 注意：钩子线程只碰内存快照，排除程序列表以快照方式注入（主线程读取 SQLite）
    hook = None
    tsf = None
    if KeyboardHook is not None:
        hook = KeyboardHook(
            on_char=engine.handle_char,
            on_delete=engine.handle_delete,
            on_ime=engine.handle_ime,
        )
        ok = hook.start()
        window.set_hook_status(ok)
        window.set_hook(hook)
        hook.set_excluded_apps(window.load_excluded_apps())
        if not ok:
            toast('警告', '键盘钩子安装失败，本次不会统计打字。请重启应用。')
        # TSF 组字监听（微软拼音等 TSF 输入法的精确中文上屏计数）
        try:
            from app.core.tsf_hook import TsfHook
            tsf = TsfHook(on_commit=hook.on_tsf_commit)
            if tsf.start():
                hook.attach_tsf(tsf)
                print('[TSF] 中文组字精确计数已启用')
            else:
                print('[TSF] 不可用，中文按 IMM/按键近似计数')
        except Exception as e:
            print(f'[TSF] 初始化失败：{e}')
    else:
        window.set_hook_status(False)
        toast('警告', '当前平台不支持键盘钩子，不会统计打字。')

    for a in startup_unlocks:
        window.notify('成就', f'解锁「{a["name"]}」，到成就页领取奖励', 'achievement')

    def on_flush():
        engine.flush()
        # 累计值成就（chars/total_acc）在数据落盘时即时判定：
        # 曾只在启动与日切判定，白天跨过 1 万字门槛要等次日才解锁（v0.8.9）
        for a in achievements.check_all(engine):
            toast('成就', f'解锁「{a["name"]}」，到成就页领取奖励', 'achievement')

    flush_timer = QTimer()
    flush_timer.timeout.connect(on_flush)
    flush_timer.start(10_000)

    roll_timer = QTimer()

    _REWARD_CN = {'makeup_card': '补签卡', 'exp_boost': '经验加成卡',
                  'exp': '经验', 'ai_pass': 'AI 训练券'}

    def on_roll():
        if engine.check_rollover():
            r = checkin.checkin_if_needed(engine.current_day())
            if r:
                toast('打卡', f'{r["date"]} 连签 {r["streak"]} 天，+{r["total_exp"]} exp',
                      'milestone' if r.get('milestone') else 'star')
                window.show_checkin_popup(r)
                if r.get('milestone'):
                    toast('里程碑', f'连签 {r["milestone"]} 天达成，礼包已发放！', 'milestone')
            for a in achievements.check_all(engine):
                toast('成就', f'解锁「{a["name"]}」，到成就页领取奖励', 'achievement')
            ev = encourage.check(engine)
            if ev:
                kind, qty = ev['reward']
                toast('鼓励',
                      f'速度跃升 {ev["ratio"]:.0%}！奖励 {_REWARD_CN.get(kind, kind)}×{qty}'
                      + ('，可用于提前体验 AI 定制训练！' if kind == 'ai_pass' else '，继续保持！'),
                      'encourage')

    roll_timer.timeout.connect(on_roll)
    roll_timer.start(30_000)

    def cleanup():
        engine.flush()
        if hook is not None:
            hook.stop()
        repo.close()

    app.aboutToQuit.connect(cleanup)

    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
