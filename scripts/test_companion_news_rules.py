"""来信纯规则与报告边界回归；固定时间和主动资料，不联网或读取用户数据。"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import unittest

from app.modules.companion.api import AgentConfig, AgentReport, SearchSource
from app.modules.companion import news, news_codec


class NewsRuleTests(unittest.TestCase):
    """防止错误排期、画像越界和不可信报告被保存为成功记忆。"""
    def config(self, **changes):
        """构造有明确兴趣的默认来信配置，覆盖值只影响本用例。"""
        return news.NewsConfig(**dict(dict(enabled=True, interests=('人工智能',)), **changes))

    def test_defaults_and_explicit_interest_limits(self):
        """默认关闭，兴趣去重后受数量与每项字数限制，不从其他资料推断。"""
        self.assertFalse(news.NewsConfig.from_values({}).enabled)
        self.assertEqual(news.normalize_interests(' AI \n游戏\nAI\nai '), ('AI', '游戏'))
        self.assertEqual(news.normalize_interests('\n'), ())
        for text in ('\n'.join('abcdef'), '字' * 41):
            with self.subTest(text=text), self.assertRaises(ValueError):
                news.normalize_interests(text)
        self.assertEqual(sum(map(len, news.normalize_interests('\n'.join(c * 40 for c in 'abcde')))), 200)
        with self.assertRaises(ValueError):
            news.NewsConfig.from_values({'companion_news_enabled': '1'})

    def test_configuration_round_trip_and_invalid_quiet_interval(self):
        """JSON 兴趣往返不损失内容；等长安静区间与非法时间不能生效。"""
        config = self.config()
        values = config.settings_values()
        self.assertEqual(json.loads(values['companion_news_interests']), ['人工智能'])
        self.assertEqual(news.NewsConfig.from_values(values), config)
        for changes in ({'quiet_start': '08:00', 'quiet_end': '08:00'}, {'time': '25:00'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.config(**changes)

    def test_quiet_hours_and_local_day_are_separate_from_statistics(self):
        """跨午夜安静时段顺延不跨日；排期不使用凌晨四点统计日。"""
        day = date(2026, 10, 20)
        self.assertEqual(news.scheduled_at(self.config(), day), datetime(2026, 10, 20, 9))
        self.assertEqual(news.scheduled_at(self.config(time='07:00'), day), datetime(2026, 10, 20, 8))
        self.assertIsNone(news.scheduled_at(self.config(time='23:00'), day))
        early = self.config(time='01:00', quiet_enabled=False)
        self.assertEqual(news.due_plan(early, datetime(2026, 10, 20, 1, 30)).task_id, 'news:2026-10-20')
        self.assertTrue(news.is_quiet(self.config(), datetime(2026, 10, 20, 23)))
        self.assertFalse(news.is_quiet(self.config(), datetime(2026, 10, 20, 8)))

    def test_grace_window_and_clock_rollback(self):
        """仅当日到期两小时窗口受理，回拨至到期前不再判为到期。"""
        config = self.config()
        for hour, minute, second, allowed in [(8, 59, 59, False), (10, 59, 0, True),
                                               (11, 0, 0, True), (11, 0, 1, False)]:
            with self.subTest(hour=hour, minute=minute, second=second):
                self.assertEqual(news.due_plan(config, datetime(2026, 10, 20, hour, minute, second)) is not None, allowed)
        self.assertIsNone(news.due_plan(replace(config, enabled=False), datetime(2026, 10, 20, 9)))

    def test_next_time_is_future_and_respects_quiet_end(self):
        """下次时间与实际到期使用同一规则；永久落在跨日安静段时不伪造日期。"""
        self.assertEqual(news.next_news_at(self.config(), datetime(2026, 10, 20, 9)), datetime(2026, 10, 21, 9))
        self.assertEqual(news.next_news_at(self.config(time='07:00'), datetime(2026, 10, 20, 7)), datetime(2026, 10, 20, 8))
        self.assertIsNone(news.next_news_at(self.config(time='23:00'), datetime(2026, 10, 20, 12)))
        tz = timezone(timedelta(hours=8))
        plan = news.due_plan(self.config(), datetime(2026, 10, 20, 9, 30, tzinfo=tz))
        self.assertEqual(plan.planned_date, '2026-10-20')

    def test_fingerprint_excludes_keys_and_changes_with_interests(self):
        """更换凭据不写入持久指纹，明确兴趣变化必须使自动任务失效。"""
        agent = AgentConfig(enabled=True, api_key='private-a', search_key='private-b')
        first = news.configuration_fingerprint(agent, self.config(), True)
        self.assertEqual(first, news.configuration_fingerprint(replace(agent, api_key='another'), self.config(), True))
        self.assertNotEqual(first, news.configuration_fingerprint(agent, self.config(interests=('游戏',)), True))
        self.assertNotEqual(first, news.configuration_fingerprint(agent, self.config(), False))

    def report(self, **changes):
        """建立带公开来源的真实结构夹具，内部不含模型轮次或凭据。"""
        item = AgentReport('request-1', '今日来信', '新动态见 [1]',
                           (SearchSource('公开资料', 'https://example.org/news', '必要摘录'),),
                           '2026-10-20T01:00:00+00:00')
        return replace(item, **changes)

    def test_report_codec_round_trips_warning_and_rejects_missing_sources(self):
        """有证据的部分报告可恢复；缺证据不得成为成功来信。"""
        report = self.report(warning='部分资料日期未核实')
        self.assertEqual(news_codec.decode_report(news_codec.encode_report(report)), report)
        with self.assertRaises(ValueError):
            news_codec.encode_report(self.report(sources=()))
        for text in ('not json', '{}', '{"reasoning":"private"}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                news_codec.decode_report(text)

    def test_report_codec_rejects_oversize_and_unsafe_source_rows(self):
        """超过正文／来源上限或危险链接时拒绝保存，不打开或请求链接。"""
        report = self.report()
        for invalid in (replace(report, summary='字' * 12001), replace(report, sources=report.sources * 9),
                        replace(report, fetched_at='2026-10-20T09:00:00'),
                        replace(report, sources=(SearchSource('x', 'http://127.0.0.1/key', ''),)),
                        replace(report, sources=(SearchSource('x', 'https://user:pass@example.org', ''),))):
            with self.subTest(invalid=invalid.topic), self.assertRaises(ValueError):
                news_codec.encode_report(invalid)
        decoded = json.loads(news_codec.encode_report(report))
        decoded['sources'][0]['snippet'] = ['wrong type']
        with self.assertRaises(ValueError):
            news_codec.decode_report(json.dumps(decoded))

    def test_report_source_rejects_ambiguous_numeric_and_control_character_hosts(self):
        """缩写数字 IP 和 URL 控制字符不能绕过公开网页地址约束。"""
        for url in ('http://127.1/x', 'http://0177.0.0.1/x', 'http://0x7f.0.0.1/x',
                    'https://example.org/\r\nprivate'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                news_codec.encode_report(self.report(sources=(SearchSource('x', url, ''),)))


if __name__ == '__main__':
    unittest.main()
