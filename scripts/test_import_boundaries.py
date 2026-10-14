"""Import guards cover aliases and submodules, as well as the supported public API path."""
from pathlib import Path
import unittest
from check_architecture import ROOT, check

class ImportBoundaryTests(unittest.TestCase):
    """公开 API 与 SQL/纯规则导入限制的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def test_sql_backend_submodules_are_rejected_from_ui(self):
        """验证 UI 不能经 SQL 后端子模块绕过导入边界。"""
        path=ROOT/'app/ui/pages/example.py'
        for source in ('import sqlite3.dbapi2 as database',
                       'from sqlite3.dbapi2 import connect',
                       'from ...storage.session import DataSession',
                       'from redis.client import Redis'):
            with self.subTest(source=source):
                self.assertTrue(check(path,source))

    def test_cross_module_repository_imports_are_rejected(self):
        """验证跨业务直接导入内部仓储被架构检查拒绝。"""
        self.assertTrue(check(ROOT/'app/modules/practice/service.py',
                              'from ..english.repository import EnglishRepository'))

    def test_public_api_imports_are_allowed(self):
        """验证跨模块使用公开 API 的依赖合法。"""
        self.assertEqual(check(ROOT/'app/modules/practice/service.py',
                               'from ..english.api import EnglishService'),[])

    def test_pure_rules_cannot_import_ui_or_network(self):
        """验证纯业务规则不能依赖 UI、网络或 SQL。"""
        path=ROOT/'app/modules/tracking/domain.py'
        for source in ('from PySide6.QtCore import QObject','import urllib.request'):
            with self.subTest(source=source):
                self.assertTrue(check(path,source))

    def test_ui_cannot_reach_a_private_sql_connection(self):
        """验证 UI 无法通过私有字段访问 SQLite 连接。"""
        self.assertTrue(check(ROOT/'app/ui/pages/example.py','connection = presenter._conn'))

if __name__=='__main__':unittest.main()
