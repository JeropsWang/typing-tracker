"""Sariana - 入口：单实例锁、初始化、后台钩子、托盘、主窗口。

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

from app import APP_NAME, APP_TAGLINE, __version__
from app.bootstrap.application import DesktopApplication
from app.bootstrap.features import DesktopQueries
from app.integrations.ai.api import AIService
from app.theme.theme_manager import ThemeManager
from app.ui.assets.app_icon import app_icon
from app.ui.main_window import MainWindow
from app.ui.tray import TrayIcon

try:
    from app.core.keyboard_hook import KeyboardHook
except Exception:  # 非 Windows 平台降级：无钩子，仅界面可用
    KeyboardHook = None

# Preserve the data directory and app.lock shared with pre-rename versions.
DEFAULT_DATA_DIR = Path.home() / 'AppData' / 'Roaming' / 'TypingTracker'


def load_balance() -> dict:
    p = Path(__file__).resolve().parent / 'config' / 'balance.json'
    return json.loads(p.read_text(encoding='utf-8'))


def load_achievements() -> dict:
    p = Path(__file__).resolve().parent / 'config' / 'achievements.json'
    return json.loads(p.read_text(encoding='utf-8'))


def default_settings(balance) -> dict:
    return {
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
        'ai_thinking': '0',
        'ai_thinking_protocol': 'auto',
    }


def ensure_default_settings(repo,balance):
    for key,value in default_settings(balance).items():
        if repo.get_setting(key) is None:
            repo.set_setting(key,value)


def apply_window_icon(app: QApplication) -> None:
    """窗口 / 任务栏图标：交付 PNG 优先，缺失时回退程序化绘制，绝不抛异常。"""
    try:
        icon = app_icon()
    except Exception as e:  # 资源缺失或 Qt 异常都不该拦住启动
        print(f'[图标] 加载失败，沿用 Qt 默认图标：{e}')
        return
    if not icon.isNull():
        app.setWindowIcon(icon)


def main() -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME, description=APP_TAGLINE)
    parser.add_argument('--data-dir', default=str(DEFAULT_DATA_DIR),
                        help='数据目录（默认 %%APPDATA%%/TypingTracker）')
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    apply_window_icon(app)
    app.setQuitOnLastWindowClosed(False)  # 关窗不退出，驻留托盘

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    # 单实例锁（防双开重复计数）
    from PySide6.QtCore import QLockFile
    lock = QLockFile(str(data_dir / 'app.lock'))
    if not lock.tryLock(100):
        QMessageBox.warning(None, APP_NAME, 'Sariana 或旧版打字管家已在运行，请勿重复启动。')
        return 1

    balance = load_balance()
    ach_defs = load_achievements()
    try:
        application=DesktopApplication(data_dir,balance,ach_defs,default_settings(balance))
    except Exception as error:
        QMessageBox.critical(None,APP_NAME,f'数据初始化失败，原有数据已保留。\n{error}')
        return 1
    repo=DesktopQueries(application)
    engine=application.counter
    checkin=application.checkin
    achievements=application.achievements
    encourage=application.encourage
    rewards=application.rewards
    get_setting=repo.get_setting

    def notify(title: str, msg: str):
        print(f'[{title}] {msg}')

    # 每天首次启动自动打卡
    checkin_result = application.startup_checkin
    if checkin_result:
        notify('打卡',
               f'{checkin_result["date"]} 连签 {checkin_result["streak"]} 天，'
               f'+{checkin_result["total_exp"]} exp')
        if checkin_result.get('milestone'):
            notify('里程碑',
                   f'连签 {checkin_result["milestone"]} 天达成，里程碑礼包已发放！')
    startup_unlocks = application.startup_unlocks
    for a in startup_unlocks:
        notify('成就', f'解锁「{a["name"]}」，到成就页领取奖励')

    tray = TrayIcon()
    tray.show()
    window = MainWindow(engine, repo, balance, tray,
                        checkin=checkin, rewards=rewards,
                        achievements=achievements,
                        theme_manager=ThemeManager(
                            app, data_dir, get_setting, repo.set_setting),
                        challenge=application.practice,
                        ai_service=AIService(repo),
                        data_dir=data_dir,application=application)
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

    # 注意：startup_unlocks 不在窗口显示前弹 toast（show_toast 会因
    # 窗口不可见而丢弃），统一在 window.show() 后补发

    def on_flush():
        application.flush()

    flush_timer = QTimer()
    flush_timer.timeout.connect(on_flush)
    flush_timer.start(2_000)

    roll_timer = QTimer()

    _REWARD_CN = {'makeup_card': '补签卡', 'exp_boost': '经验加成卡',
                  'exp': '经验', 'ai_pass': 'AI 训练券'}

    def on_roll():
        if engine.check_rollover():
            application.flush()
            def checked(result):
                if result:
                    toast('打卡',f"{result['date']} 连签 {result['streak']} 天，+{result['total_exp']} exp",
                          'milestone' if result.get('milestone') else 'star')
                    window.show_checkin_popup(result)
            window._tasks.resolve(checkin.checkin_if_needed(engine.current_day()),checked)
            def encouraged(event):
                if event:
                    kind,qty=event['reward']
                    toast('鼓励',f"速度跃升 {event['ratio']:.0%}！奖励 {_REWARD_CN.get(kind,kind)}×{qty}",'encourage')
            window._tasks.resolve(encourage.check(engine),encouraged)

    roll_timer.timeout.connect(on_roll)
    roll_timer.start(30_000)

    def cleanup():
        application.stop_accepting()
        flush_timer.stop()
        roll_timer.stop()
        if window._companion is not None:
            window._companion.shutdown()
        if hasattr(window,'_challenge_page'):
            window._challenge_page._cancel_generation()
            window._challenge_page.chaos_panel.hide()
        window._english_page._cancel_request()
        if tsf is not None:
            tsf.stop()
        if hook is not None:
            hook.stop()
        try:
            application.close()
        except Exception as error:
            QMessageBox.warning(window,'统计未保存',f'最后一次统计保存失败：{error}')

    app.aboutToQuit.connect(cleanup)

    window.show()
    if startup_unlocks:
        QTimer.singleShot(600, lambda: [
            toast('成就', f'解锁「{a["name"]}」，到成就页领取奖励', 'achievement')
            for a in startup_unlocks])
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
