"""Import guards cover aliases and submodules, as well as the supported public API path."""
from pathlib import Path
import unittest
from check_architecture import ROOT, check

class ImportBoundaryTests(unittest.TestCase):
    def test_sql_backend_submodules_are_rejected_from_ui(self):
        path=ROOT/'app/ui/pages/example.py'
        for source in ('import sqlite3.dbapi2 as database',
                       'from sqlite3.dbapi2 import connect',
                       'from ...storage.session import DataSession',
                       'from redis.client import Redis'):
            with self.subTest(source=source):
                self.assertTrue(check(path,source))

    def test_cross_module_repository_imports_are_rejected(self):
        self.assertTrue(check(ROOT/'app/modules/practice/service.py',
                              'from ..english.repository import EnglishRepository'))

    def test_public_api_imports_are_allowed(self):
        self.assertEqual(check(ROOT/'app/modules/practice/service.py',
                               'from ..english.api import EnglishService'),[])

    def test_pure_rules_cannot_import_ui_or_network(self):
        path=ROOT/'app/modules/tracking/domain.py'
        for source in ('from PySide6.QtCore import QObject','import urllib.request'):
            with self.subTest(source=source):
                self.assertTrue(check(path,source))

    def test_ui_cannot_reach_a_private_sql_connection(self):
        self.assertTrue(check(ROOT/'app/ui/pages/example.py','connection = presenter._conn'))

if __name__=='__main__':unittest.main()
