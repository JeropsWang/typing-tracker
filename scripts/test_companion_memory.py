"""记忆能力和可选源码索引的隔离回归，不读本机密钥与真实用户记录。"""
from pathlib import Path
from contextlib import closing
import tempfile
import unittest
import hashlib
import json
from app.integrations.development_index import DevelopmentIndexService, CODE_ENTRIES
from app.ui.companion.memory_presenter import MemoryPresenter
from test_companion_news_desktop import NewsDesktopTests, STAMP


class MemoryTests(NewsDesktopTests):
    """使用同一真实来信快照验证删除、兴趣提交与保存语义。"""
    def test_forget_today_keeps_auto_dedup(self):
        """删除正文后保留当天去重墓碑，五十次唤醒不会再次产生付费生成。"""
        self.enable()
        self.controller.tick()
        self.wait_report()
        presenter = MemoryPresenter(self.queries, self.application.news_commands)
        original = presenter.snapshot().reports[0]
        presenter.forget(original.task_id, 'forget-once').result(5)
        self.assertFalse(presenter.snapshot().reports)
        for _ in range(50):
            self.controller.tick()
        self.assertEqual(len(self.model_calls), 1)
        self.assertEqual(presenter.snapshot().tasks[0].task_id, original.task_id)

    def test_clear_interests_disables_schedule(self):
        """明确清空兴趣同时关闭排期，不保留启用但没有画像的无效配置。"""
        self.enable()
        presenter = MemoryPresenter(self.queries, self.application.news_commands)
        presenter.save_interests('', 'clear-once').result(5)
        self.assertFalse(presenter.snapshot().config.enabled)
        self.assertEqual(presenter.snapshot().config.interests, ())


class DevelopmentIndexTests(unittest.TestCase):
    """可选索引缺失、伪路径与打包模式均不影响产品记忆。"""
    def test_index_cannot_escape_code_allowlist(self):
        """任意外部路径和 URL 均被固定代码入口白名单拒绝。"""
        with closing(DevelopmentIndexService()) as service:
            with self.assertRaises(ValueError):
                service.snapshot(('../../private.txt',)).result(5)

    def test_missing_index_and_packaged_fallback(self):
        """冻结包没有源码索引时仍给模块定位，不依赖 Go／MCP。"""
        with closing(DevelopmentIndexService(frozen=True)) as service:
            snapshot = service.snapshot(tuple(CODE_ENTRIES)).result(5)
            self.assertIn('源码', snapshot.status)
            self.assertTrue(all(not entry.local_path for entry in snapshot.entries))
            self.assertTrue(all(entry.module for entry in snapshot.entries))

    def test_source_change_marks_optional_index_stale(self):
        """有效本地索引仅核对固定源码摘要，源码修改后明确过期，不伪称 aligned。"""
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / '.local') as directory:
            source = Path(directory)
            ref = next(iter(CODE_ENTRIES))
            path = source / ref
            path.parent.mkdir(parents=True)
            path.write_bytes(b'original')
            (source / '.aoci').mkdir()
            (source / '.aoci/baseline.json').write_text(json.dumps({'version': 1, 'files': {
                ref: {'sha256': hashlib.sha256(b'original').hexdigest()}}}), encoding='utf-8')
            (source / 'aoci.code.txt').write_text('===' + path.parent.as_posix() + '/===\n'
                + path.name + '[DB8T]: F:示例职责 | R:- | A:api | S:-', encoding='utf-8')
            with closing(DevelopmentIndexService(root=source)) as service:
                current = service.snapshot((ref,)).result(5)
                self.assertIn('摘要匹配', current.entries[0].state)
                self.assertIn('示例职责', current.entries[0].semantics)
                path.write_bytes(b'changed')
                stale = service.snapshot((ref,)).result(5)
                self.assertIn('过期', stale.entries[0].state)
                self.assertIn('未核验', stale.status)
