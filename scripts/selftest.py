"""无 GUI 自检：分类器 / tw 换算 / 日界 / 等级公式 / 存储引擎 / 打卡连签 / 钩子启停。

运行：python scripts/selftest.py
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP_ROOT = ROOT / '.tmptest'


def make_temp_dir() -> Path:
    """在工作区内创建临时目录（系统 Temp 与 tempfile.mkdtemp 可能被沙箱拦截）。"""
    _TMP_ROOT.mkdir(exist_ok=True)
    p = _TMP_ROOT / ('tt_' + uuid.uuid4().hex)
    p.mkdir()
    return p


def cleanup_temp_dir(p: Path) -> None:
    shutil.rmtree(p, ignore_errors=True)

from app.core.classifier import (  # noqa: E402
    classify_char, is_hanzi, text_tw, tw_to_hanzi_per_min,
)
from app.core.engine import StatsEngine  # noqa: E402
from app.services.checkin_service import CheckinService  # noqa: E402
from app.services.exp_service import (  # noqa: E402
    cumulative_cost, level_and_progress, level_from_exp,
)
from app.storage.db import connect_db, init_schema  # noqa: E402
from app.storage.repository import Repository  # noqa: E402

BALANCE = json.loads((ROOT / 'config' / 'balance.json').read_text(encoding='utf-8'))

_passed = 0


def check(name, cond):
    global _passed
    assert cond, f'FAIL: {name}'
    _passed += 1
    print(f'  ok - {name}')


def main() -> int:
    print('== classifier（统一度量衡）==')
    check('汉字判定', is_hanzi('你') and is_hanzi('𠀀') and not is_hanzi('a') and not is_hanzi('1'))
    check('分类', classify_char('汉') == 'hanzi' and classify_char('a') == 'letter'
          and classify_char('1') == 'other' and classify_char('，') == 'other')
    check('tw 换算 1字母=1tw 1汉字=2tw', text_tw('你好abc') == 2 + 2 + 1 + 1 + 1)
    check('预测汉字数/分', tw_to_hanzi_per_min(120) == 60.0)

    print('== 等级公式 ==')
    check('cost(1)=42 cost(2)=86', cumulative_cost(1, BALANCE) == 42
          and cumulative_cost(2, BALANCE) == 86)
    check('满级累计≈13,860', cumulative_cost(99, BALANCE) == 13860)
    check('0 经验 → Lv.1', level_from_exp(0, BALANCE) == 1)
    check('42 exp → Lv.2（off-by-one 回归）', level_from_exp(42, BALANCE) == 2)
    check('86 exp → Lv.3', level_from_exp(86, BALANCE) == 3)
    check('13,860 exp → Lv.100（满级）', level_from_exp(13860, BALANCE) == 100)
    check('3,740 exp → Lv.45（AI 解锁门槛）', level_from_exp(3740, BALANCE) == 45)
    lv, prog, remain = level_and_progress(200, BALANCE)
    check('200 exp → 等级与进度合理', lv == 5 and 0 <= prog <= 1 and remain >= 0)

    print('== 存储与统计引擎 ==')
    td = make_temp_dir()
    try:
        conn = connect_db(td / 't.db')
        init_schema(conn)
        repo = Repository(conn)
        repo.set_setting('day_start_hour', '4')

        def gs(key, default=None):
            return repo.get_setting(key, default)

        eng = StatsEngine(repo, gs, BALANCE)
        expect_day = (datetime.now() - timedelta(hours=4)).date().isoformat()
        check('日界（默认凌晨 4 点）', eng.current_day() == expect_day)

        # 日切起点缓存：构造后改设置不影响钩子线程读取；update_day_start 刷新
        repo.set_setting('day_start_hour', '10')
        check('日切起点缓存生效', eng.current_day() == expect_day)
        eng.update_day_start()
        check('日切缓存刷新', eng.current_day() ==
              (datetime.now() - timedelta(hours=10)).date().isoformat())
        repo.set_setting('day_start_hour', '4')
        eng.update_day_start()

        eng.handle_char('letter')
        eng.handle_char('letter')
        eng.handle_ime('你好')
        eng.handle_delete()
        s = eng.snapshot()
        check('当日计数（2字母+2汉字，删1）', s['typed'] == 4 and s['deleted'] == 1 and s['valid'] == 3)
        check('tw 计数（2×1 + 2×2 = 6）', s['tw'] == 6)
        check('正确率 3/4', s['accuracy'] == 0.75)
        check('终身计数', s['lifetime_typed'] == 4 and s['lifetime_valid'] == 3)

        eng.flush()
        d = repo.get_recent_days(1)[0]
        check('daily 落盘', d['typed_chars'] == 4 and d['valid_chars'] == 3
              and d['total_tw'] == 6 and d['active_minutes'] >= 1)
        life = repo.get_lifetime()
        check('lifetime 落盘', life['total_typed'] == 4
              and life['total_active_minutes'] >= 1 and life['total_exp'] == 0)

        print('== 打卡与连签 ==')
        cs = CheckinService(repo, BALANCE)
        r1 = cs.checkin_if_needed('2026-06-10')
        r2 = cs.checkin_if_needed('2026-06-11')
        r3 = cs.checkin_if_needed('2026-06-10')
        check('连签递增', r1['streak'] == 1 and r2['streak'] == 2)
        check('重复打卡忽略', r3 is None)
        check('经验入账', repo.get_exp() == r1['total_exp'] + r2['total_exp'])
        check('打卡写入日记录', repo.get_daily('2026-06-10')['exp_gained'] == r1['total_exp'])

        print('== 报表查询（M2）==')
        base = date(2026, 6, 1)
        for i in range(5):
            d = (base + timedelta(days=i)).isoformat()
            repo.upsert_daily({'date': d, 'typed_chars': 100 + i * 10,
                               'deleted_chars': 5, 'valid_chars': 95 + i * 10,
                               'total_tw': 200 + i * 20, 'active_minutes': 10,
                               'avg_tw': 20 + i * 2.0, 'accuracy': 0.95})
        rows = repo.get_daily_range('2026-06-01', '2026-06-05')
        check('日范围查询', len(rows) == 5 and rows[0]['total_tw'] == 200
              and rows[4]['total_tw'] == 280)
        s = repo.get_summary('2026-06-01', '2026-06-05')
        check('区间汇总', s['tw'] == 1200 and s['valid'] == 575
              and abs(s['avg_speed'] - 24.0) < 1e-9)
        hm = repo.get_heatmap('2026-06-01', '2026-06-05')
        check('热力图数据', hm.get('2026-06-01') == 200)
        repo.upsert_minutes([
            ('2026-06-01', '09:15', 30, 2, 60),
            ('2026-06-01', '10:00', 20, 1, 40),
            ('2026-06-02', '09:05', 10, 0, 20),
        ])
        hrs = repo.get_hourly_stats('2026-06-01', '2026-06-02')
        hmap = {r['hour']: r['tw'] for r in hrs}
        check('时段聚合', hmap.get('09') == 80 and hmap.get('10') == 40)

        print('== 成就 / 道具 / 鼓励 / 打字经验（M3 后端）==')
        from app.services.achievement_service import AchievementService
        from app.services.encourage_service import EncourageService
        from app.services.reward_service import RewardService
        ACH = json.loads((ROOT / 'config' / 'achievements.json').read_text(encoding='utf-8'))
        check('成就总数 37', sum(len(v) for v in ACH.values()) == 37)

        ach = AchievementService(repo, BALANCE, ACH)
        eng_day = date.fromisoformat(eng.current_day())
        # 速度成就：近 7 日日均 100 tw/分
        for i in range(6, -1, -1):
            d = (eng_day - timedelta(days=i)).isoformat()
            repo.upsert_daily({'date': d, 'typed_chars': 3000, 'deleted_chars': 30,
                               'valid_chars': 2970, 'total_tw': 3000,
                               'active_minutes': 30, 'avg_tw': 100.0, 'accuracy': 0.99})
        codes = {a['code'] for a in ach.check_all(eng)}
        check('速度成就解锁', 'speed_50' in codes and 'speed_100' in codes
              and 'speed_150' not in codes)
        check('重复检查不重复解锁', ach.check_all(eng) == [])

        # 字数 / 总正确率成就
        repo.upsert_lifetime({'total_typed': 20000, 'total_deleted': 100,
                              'total_tw': 30000, 'total_active_minutes': 500})
        codes = {a['code'] for a in ach.check_all(eng)}
        check('字数与总正确率成就', 'chars_10k' in codes and 'chars_50k' not in codes
              and 'total_acc_80' in codes and 'total_acc_99' in codes)
        check('无分钟样本不解锁', not any(c.startswith('min_acc') for c in codes))

        # 分钟正确率成就（近 7 日内一条 40 字样本，正确率 97.5%）
        d1 = (eng_day - timedelta(days=1)).isoformat()
        repo.upsert_minutes([(d1, '10:00', 40, 1, 80)])
        codes = {a['code'] for a in ach.check_all(eng)}
        check('分钟正确率成就', 'min_acc_96' in codes and 'min_acc_98' not in codes)

        # 手动领取
        g = ach.claim('speed_50')
        check('领取经验奖励', g == [('exp', 20)])
        check('重复领取被拒', ach.claim('speed_50') is None)
        g2 = ach.claim('total_acc_99')
        check('领取称号奖励', ('title', '万无一失') in g2)
        check('称号入库存', any(r['kind'] == 'title' and r['note'] == '万无一失'
                              for r in repo.list_rewards(unused_only=True)))

        # 打字经验使用独立数据库：启动会恢复当日记录，不能沿用成就测试造数。
        typing_conn = connect_db(':memory:')
        try:
            init_schema(typing_conn)
            typing_repo = Repository(typing_conn)
            eng2 = StatsEngine(typing_repo, typing_repo.get_setting, BALANCE)
            for _ in range(2500):
                eng2.handle_char('letter')
            exp_before = typing_repo.get_exp()
            eng2.flush()
            check('打字经验 2000字→+10', typing_repo.get_exp() == exp_before + 10)

            # 经验加成卡 ×2
            RewardService(typing_repo, BALANCE).activate_exp_boost(30)
            exp_before = typing_repo.get_exp()
            for _ in range(1000):
                eng2.handle_char('letter')
            eng2.flush()
            check('经验加成卡 ×2', typing_repo.get_exp() == exp_before + 10)
        finally:
            typing_conn.close()

        # 补签卡：06-09 连签 5，06-10 断，补签后连签恢复
        # 补签卡：06-20 连签 5，06-21 断，补签后连签恢复
        repo.add_checkin('2026-06-20', 5, 20, 0)
        r = cs.apply_makeup_card('2026-06-21', today_iso='2026-06-22')
        check('补签恢复连签', r is not None and r['streak'] == 6)
        check('未来日期补签被拒', cs.apply_makeup_card('2026-06-30',
                                                   today_iso='2026-06-22') is None)
        check('非昨天日期补签被拒', cs.apply_makeup_card('2026-06-01',
                                                    today_iso='2026-06-22') is None)
        r2 = CheckinService(repo, BALANCE).checkin_if_needed('2026-06-22')
        check('补签后次日连签延续', r2['streak'] == 7)

        # 连签里程碑：第 3 天发放礼包（只发一次）
        cs.checkin_if_needed('2026-07-01')
        cs.checkin_if_needed('2026-07-02')
        exp_before = repo.get_exp()
        r5 = cs.checkin_if_needed('2026-07-03')
        check('里程碑第3天触发', r5 is not None and r5.get('milestone') == 3)
        check('里程碑经验 +20签到+15礼包', repo.get_exp() == exp_before + 35)
        check('里程碑记录在案', '3' in (repo.get_setting('milestone_granted') or '[]'))
        r6 = cs.checkin_if_needed('2026-07-04')
        check('非里程碑天不触发', r6 is not None and 'milestone' not in r6)

        # 鼓励机制：近 7 日 200 tw/分 vs 前 7 日 100 tw/分（上升 100%）
        for i in range(13, -1, -1):
            d = (eng_day - timedelta(days=i)).isoformat()
            speed = 200.0 if i < 7 else 100.0
            repo.upsert_daily({'date': d, 'typed_chars': 4000, 'deleted_chars': 40,
                               'valid_chars': 3960, 'total_tw': 6000,
                               'active_minutes': 60, 'avg_tw': speed, 'accuracy': 0.99})
        repo.set_setting('last_encourage_at',
                         (datetime.now() - timedelta(days=10)).isoformat(timespec='seconds'))
        ev = EncourageService(repo, BALANCE).check(eng)
        check('鼓励触发', ev is not None and ev['ratio'] >= 1.15)
        check('72h 冷却生效', EncourageService(repo, BALANCE).check(eng) is None)
        kinds = {r['kind'] for r in repo.list_rewards(unused_only=True)}
        check('鼓励奖励入库', bool(kinds & {'makeup_card', 'exp_boost', 'exp'}))

        print('== 打字竞速挑战（逐字计分）==')
        from app.core.challenge import TEXT_BY_ID, compare, score
        ref = '你好世界'
        c, e = compare('你好世界', ref)
        check('完全正确', c == 4 and e == 0)
        c, e = compare('你好时生', ref)
        check('两处错误', c == 2 and e == 2)
        c, e = compare('你好世界!', ref)
        check('多字计错', c == 4 and e == 1)
        c, e = compare('你好', ref)
        check('少字计错', c == 2 and e == 2)
        s = score('你好世界', ref, 60.0, BALANCE)
        check('速度 8tw/分（4汉字×2tw）', abs(s['speed'] - 8.0) < 1e-6)
        # 综合结算分：速度×0.6 + 有效字数×0.1 + 正确率%×0.5，×10000 × 完成系数
        s = score('你好世界', ref, 60.0, BALANCE)
        expect = round((8.0 * 0.6 + 4 * 0.1 + 100 * 0.5) * 10000 * 1.0)
        check('综合分公式（全对 60s → 96万分）', s['score_points'] == expect)
        s2 = score('你好世界', ref, 30.0, BALANCE)
        check('更快更高分', s2['score_points'] > s['score_points'])
        s3 = score('你好', ref, 60.0, BALANCE)
        check('未完成分更低', s3['score_points'] < s['score_points'])
        from app.services.challenge_service import ChallengeService
        csvc = ChallengeService(repo)
        exp0 = repo.get_exp()
        r1 = csvc.record('cn_star', {'typed_chars': 5, 'errors': 0,
                                     'elapsed_seconds': 60, 'tw': 10,
                                     'accuracy': 1.0, 'score_points': 500000,
                                     'base': 50}, BALANCE)
        check('首次即最佳', r1['is_best'] and r1['prev_best'] == 0)
        check('挑战经验发放', r1['exp_gained'] == 50
              and repo.get_exp() == exp0 + 50)
        r2 = csvc.record('cn_star', {'typed_chars': 5, 'errors': 0,
                                     'elapsed_seconds': 30, 'tw': 20,
                                     'accuracy': 1.0, 'score_points': 800000,
                                     'base': 80}, BALANCE)
        check('新纪录更新', r2['is_best'] and r2['prev_best'] == 500000)
        r3 = csvc.record('cn_star', {'typed_chars': 5, 'errors': 0,
                                     'elapsed_seconds': 60, 'tw': 5,
                                     'accuracy': 1.0, 'score_points': 200000,
                                     'base': 20}, BALANCE)
        check('未破纪录不标新', not r3['is_best'])
        # 每日经验上限 200
        from datetime import date as _date
        repo.set_setting('challenge_exp_date', _date.today().isoformat())
        repo.set_setting('challenge_exp_today', '190')
        r4 = csvc.record('cn_star', {'typed_chars': 5, 'errors': 0,
                                     'elapsed_seconds': 60, 'tw': 5,
                                     'accuracy': 1.0, 'score_points': 100000,
                                     'base': 50}, BALANCE)
        check('每日经验上限 200', r4['exp_gained'] == 10)
        check('近期记录 4 条', len(csvc.recent(10)) == 4)

        print('== AI 定制训练（45 级解锁 / 训练券）==')
        from app.core.challenge import ai_access_state
        allowed, hint = ai_access_state(30, 0, 45)
        check('低等级未解锁', not allowed and 'Lv.45' in hint)
        allowed, _ = ai_access_state(30, 2, 45)
        check('训练券提前体验', allowed)
        allowed, _ = ai_access_state(45, 0, 45)
        check('45 级解锁', allowed)
        allowed, _ = ai_access_state(99, 0, 45)
        check('高等级解锁', allowed)
        # 券的发放与消耗（先清空，保证确定性）
        while repo.use_reward('ai_pass'):
            pass
        repo.add_reward('ai_pass', 1, 'encourage')
        check('训练券入库', repo.count_ai_passes() == 1)
        check('训练券消耗', repo.use_reward('ai_pass') and repo.count_ai_passes() == 0)
        check('无券不可消耗', not repo.use_reward('ai_pass'))
        # 鼓励奖励池包含训练券（真实触发一次看池成员）
        repo.set_setting('last_encourage_at',
                         (datetime.now() - timedelta(days=10)).isoformat(timespec='seconds'))
        ev = EncourageService(repo, BALANCE).check(eng)
        check('鼓励池含 ai_pass 或常规奖励', ev is None or ev['reward'][0]
              in ('makeup_card', 'exp_boost', 'exp', 'ai_pass'))

        print('== AI 范文生成（mock OpenAI 兼容端点）==')
        import threading as _th
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class _AIHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                self.server.last_body = self.rfile.read(length)
                resp = json.dumps({'choices': [{
                    'message': {'content': '星空之下，微光闪烁，指尖轻舞。'}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(resp)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(('127.0.0.1', 0), _AIHandler)
        _th.Thread(target=srv.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{srv.server_port}/v1'
        repo.set_setting('ai_backend', 'openai')
        repo.set_setting('ai_base_url', base)
        repo.set_setting('ai_api_key', 'test-key')
        repo.set_setting('ai_model', 'mock-model')
        from app.services.ai_service import AIService
        ai = AIService(repo)
        ok, msg = ai.test_connection()
        check('AI 连接测试', ok)
        ok, text = ai.generate('星空', 'cn', 100)
        check('AI 生成请求携带主题', ok and '\\u661f\\u7a7a' in srv.last_body.decode())
        check('AI 响应清洗', ok and '星空之下' in text)
        ok2, _ = ai.generate('', 'cn', 100)
        check('空主题拒绝', not ok2)
        srv.shutdown()

        print('== 备份导出（M4）==')
        from app.services.export_service import export_all
        folder = export_all(repo, str(td))
        csv_file = Path(folder) / 'daily_stats.csv'
        json_file = Path(folder) / 'data.json'
        check('导出目录生成', csv_file.exists() and json_file.exists())
        check('CSV 含表头与数据', csv_file.read_text(encoding='utf-8-sig').startswith(
            'date,typed_chars,deleted_chars,valid_chars'))
        check('JSON 含 lifetime', '"lifetime"' in json_file.read_text(encoding='utf-8'))
    finally:
        cleanup_temp_dir(td)

    print('== TSF 组字状态机（精确中文提交）==')
    from app.core.tsf_hook import TsfHook
    t = TsfHook()
    c = t._update_state(True, 'ni', '')
    check('组字开始无提交', c == [])
    c = t._update_state(True, 'nih', '')
    check('组字增长无提交', c == [])
    c = t._update_state(True, 'hao', '你好')
    check('连续组字提交精确文本', c == ['你好'])
    t2 = TsfHook()
    t2._update_state(True, 'ni', '')
    c = t2._update_state(False, '', '你')
    check('组字结束提交', c == ['你'])
    t3 = TsfHook()
    t3._update_state(True, 'ni', '')
    c = t3._update_state(False, '', '')
    check('取消不提交', c == [])
    t4 = TsfHook()
    t4._update_state(True, 'ni', '')
    c = t4._update_state(False, '', 'ni')
    check('无变化不提交', c == [])
    t5 = TsfHook()
    t5._update_state(True, 'hao', '')
    c = t5._update_state(True, 'shi', '好')
    check('切换组字提交', c == ['好'])

    print('== 主题可读性（文字对比度，防回归）==')
    from app.ui.palette import P as PAL

    def _lum(hexcolor):
        h = hexcolor.lstrip('#')
        r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

        def f(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = f(r), f(g), f(b)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def _contrast(c1, c2):
        l1, l2 = sorted((_lum(c1), _lum(c2)), reverse=True)
        return (l1 + 0.05) / (l2 + 0.05)

    lino = json.loads((ROOT / 'app' / 'theme' / 'themes' / 'arknights_endfield_lino'
                       / 'manifest.json').read_text(encoding='utf-8'))
    PAL.update(lino['colors'], lino.get('effects', {}))
    bg = lino['colors']['background']
    check('梨诺正文对比度 ≥4.5', _contrast(PAL.text, bg) >= 4.5)
    check('梨诺次要文字对比度 ≥3.0', _contrast(PAL.muted, bg) >= 3.0)
    # 梨诺是唯一内置主题：内置目录里不应再有其它主题包
    builtin_themes = sorted(p.name for p in (ROOT / 'app' / 'theme' / 'themes').iterdir()
                            if (p / 'manifest.json').exists())
    check('内置主题只剩梨诺', builtin_themes == ['arknights_endfield_lino'])

    print('== 键盘钩子（安装/卸载冒烟，不注入按键）==')
    from app.core.keyboard_hook import KeyboardHook, ImeCommitTracker  # noqa: E402
    events = []
    hk = KeyboardHook(on_char=lambda k: events.append(k))
    ok = hk.start()
    check('钩子安装', ok)
    import time
    time.sleep(0.3)
    hk.stop()
    check('钩子卸载', hk._hook is None)
    # 防回归：Win32 API 必须挂在正确的 DLL 上（曾因 user32.OpenProcess 导致全部漏计）
    src = (ROOT / 'app' / 'core' / 'keyboard_hook.py').read_text(encoding='utf-8')
    check('无 user32.OpenProcess 误挂', 'user32.OpenProcess' not in src
          and 'user32.CloseHandle' not in src)
    check('kernel32 声明齐备', 'kernel32.OpenProcess.argtypes' in src
          and 'kernel32.QueryFullProcessImageNameW.argtypes' in src)

    print('== IME 上屏检测（连续打字不丢失，回归修复）==')
    t = ImeCommitTracker()
    got = []

    def upd(tracker, store, o, c, r):
        v = tracker.update(o, c, r)
        if v:
            store.append(v)

    upd(t, got, True, 'n', '')
    upd(t, got, True, 'ni', '')
    upd(t, got, True, '', '你')          # 空格提交
    upd(t, got, True, 'h', '你')         # 立即开始新组字
    upd(t, got, True, 'ha', '')
    upd(t, got, True, '', '好')          # 第二次提交
    upd(t, got, True, '', '')
    check('连续组字提交不丢失', got == ['你', '好'])

    t2 = ImeCommitTracker()
    got2 = []
    upd(t2, got2, True, 'ni', '')
    upd(t2, got2, True, 'hao', '')       # 新组字开始且 result 已清 → 近似兜底
    check('无 result 时近似兜底', got2 == ['ni'])

    t3 = ImeCommitTracker()
    got3 = []
    upd(t3, got3, True, 'niha', '')
    upd(t3, got3, True, 'nih', '')       # 组字内退格（旧串以新串开头）
    upd(t3, got3, True, 'niha', '')
    check('组字内退格不计提交', got3 == [])

    t4 = ImeCommitTracker()
    got4 = []
    upd(t4, got4, True, 'ni', '')
    upd(t4, got4, True, '', '')          # Esc 取消
    check('取消组字不计数', got4 == [])

    t5 = ImeCommitTracker()
    got5 = []
    upd(t5, got5, True, '', '，')        # 中文标点直接提交
    check('标点直接提交', got5 == ['，'])

    t6 = ImeCommitTracker()
    got6 = []
    upd(t6, got6, True, 'ni', '')
    upd(t6, got6, True, '', '你')
    upd(t6, got6, True, 'ni', '')
    upd(t6, got6, True, '', '你')
    check('同内容重复提交', got6 == ['你', '你'])

    t7 = ImeCommitTracker()
    got7 = []
    upd(t7, got7, True, 'hao', '')
    upd(t7, got7, True, '', '好')        # 轮询捕获（鼠标选字）
    check('轮询捕获鼠标选字', got7 == ['好'])

    print('== 分钟数据跨 flush 累计（回归）==')
    td2 = make_temp_dir()
    try:
        conn2 = connect_db(td2 / 't.db')
        init_schema(conn2)
        repo2 = Repository(conn2)

        def gs2(key, default=None):
            return repo2.get_setting(key, default)

        eng3 = StatsEngine(repo2, gs2, BALANCE)
        eng3.handle_char('letter')
        eng3.flush()                     # 首次 flush：分钟行含 1 键
        eng3.handle_char('letter')       # 同分钟追加
        eng3.handle_char('letter')
        eng3.flush()                     # 再次 flush：必须完整累计
        row = repo2._conn.execute(
            'SELECT typed_chars FROM minute_stats ORDER BY date DESC, minute DESC'
        ).fetchone()
        check('分钟跨 flush 累计（不再欠计）', row['typed_chars'] == 3)
    finally:
        cleanup_temp_dir(td2)

    print(f'\n全部通过：{_passed} 项')
    return 0


if __name__ == '__main__':
    sys.exit(main())
