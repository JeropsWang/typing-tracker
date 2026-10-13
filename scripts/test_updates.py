"""Isolated GitHub responses, verified downloads and real-worker update shutdown."""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from app.integrations.updates.service import (API_URL, UpdateService, UpdateCancelled,
    parse_release, stable_version, installation_kind, VerifiedInstaller, InstallerHandoff,
    run_installer_helper, _Redirects)
from app.bootstrap.application import DesktopApplication
from app.ui.updates import UpdateController, UpdateExitCoordinator, UpdatesWidget
from PySide6.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
BALANCE = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
BODY = b'isolated mock installer payload'
DIGEST = hashlib.sha256(BODY).hexdigest()
BASE = 'https://github.com/JeropsWang/typing-tracker/releases'


def pump_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def payload(version='1.0.0', digest=True):
    installer = f'Sariana-{version}-windows-x64-setup.exe'
    checksum_name = f'Sariana-{version}-SHA256SUMS.txt'
    checksum = f'{DIGEST}  {installer}\n'.encode()
    result = dict(tag_name=f'v{version}', html_url=f'{BASE}/tag/v{version}', draft=False, prerelease=False,
        assets=[dict(name=installer, size=len(BODY), digest=f'sha256:{DIGEST}' if digest else None,
                     browser_download_url=f'{BASE}/download/v{version}/{installer}'),
                dict(name=f'Sariana-{version}-windows-x64-portable.zip', size=1,
                     browser_download_url=f'{BASE}/download/v{version}/Sariana-{version}-windows-x64-portable.zip'),
                dict(name=checksum_name, size=len(checksum), browser_download_url=f'{BASE}/download/v{version}/{checksum_name}')])
    return result, checksum


class FakeOpener:
    def __init__(self, entries):
        self.entries = entries
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request.full_url)
        result = self.entries[request.full_url]
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(result)


class UpdateTransportTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.local').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.local')
        self.cache = Path(self.temp.name) / 'updates'

    def tearDown(self):
        self.temp.cleanup()

    def service(self, *, digest=True, body=BODY):
        data, checksum = payload(digest=digest)
        release = parse_release(data, '0.9.4')
        opener = FakeOpener({API_URL: json.dumps(data).encode(), release.installer.url: body,
                             release.checksums.url: checksum})
        return UpdateService(self.cache, '0.9.4', opener=opener), release, opener

    def test_numeric_versions_ignore_old_draft_prerelease_and_invalid(self):
        self.assertGreater(stable_version('v0.10.0'), stable_version('0.9.4'))
        for changes in ({'draft': True}, {'prerelease': True}, {'tag_name': 'v1.0.0-rc1'}, {'tag_name': 'invalid'}):
            data, _ = payload()
            data.update(changes)
            self.assertIsNone(parse_release(data, '0.9.4'))
        for version in ('0.9.4', '0.9.3'):
            self.assertIsNone(parse_release(payload(version)[0], '0.9.4'))

    def test_repository_asset_host_and_safe_release_name_validation(self):
        data, _ = payload()
        data['html_url'] = 'https://github.com/other/repository/releases/tag/v1.0.0'
        with self.assertRaises(ValueError):
            parse_release(data, '0.9.4')
        data, _ = payload()
        data['assets'][0]['browser_download_url'] = 'https://example.com/installer.exe'
        self.assertIsNone(parse_release(data, '0.9.4').installer)
        with self.assertRaises(ValueError):
            _Redirects().redirect_request(None, None, 302, '', {}, 'http://github.com/file')
        with self.assertRaises(ValueError):
            _Redirects().redirect_request(None, None, 302, '', {}, 'https://evil.example/file')

    def test_size_and_digest_verified_without_checksum_fetch(self):
        service, release, opener = self.service()
        self.assertEqual(service.check(), release)
        progress = []
        installer = service.download(release, threading.Event(), lambda *args: progress.append(args))
        self.assertEqual(installer.verify().path.read_bytes(), BODY)
        self.assertEqual(progress[-1], (len(BODY), len(BODY)))
        self.assertNotIn(release.checksums.url, opener.requests)

    def test_checksum_fallback_and_missing_or_ambiguous_checksum(self):
        service, release, opener = self.service(digest=False)
        self.assertEqual(service.download(release, threading.Event()).digest, DIGEST)
        checksum = opener.entries[release.checksums.url]
        opener.entries[release.checksums.url] = b'x' * len(checksum)
        with self.assertRaises(ValueError):
            service.download(release, threading.Event())
        data, _ = payload(digest=False)
        data['assets'] = data['assets'][:1]
        with self.assertRaises(ValueError):
            service.download(parse_release(data, '0.9.4'), threading.Event())

    def test_corrupt_truncated_and_oversized_downloads_remove_partial(self):
        for body in (BODY[:-1], BODY + b'x', b'x' * len(BODY)):
            service, release, _ = self.service(body=body)
            with self.assertRaises(ValueError):
                service.download(release, threading.Event())
            self.assertFalse(list(self.cache.glob('*.partial')))
            self.assertFalse(list(self.cache.glob('*.exe')))

    def test_cancel_mid_download_and_install_revalidation(self):
        service, release, _ = self.service()
        cancel = threading.Event()
        with self.assertRaises(UpdateCancelled):
            service.download(release, cancel, lambda *_: cancel.set())
        self.assertFalse(list(self.cache.glob('*')))
        installer = service.download(release, threading.Event())
        installer.path.write_bytes(b'x' * len(BODY))
        with self.assertRaises(ValueError):
            installer.verify()

    def test_rate_limit_and_network_errors_have_actionable_messages(self):
        for failure in (HTTPError(API_URL, 429, 'limited', {}, None),
                        HTTPError(API_URL, 403, 'limited', {}, None), URLError('offline')):
            service = UpdateService(self.cache, '0.9.4', opener=FakeOpener({API_URL: failure}))
            with self.assertRaises(RuntimeError):
                service.check()

    def test_source_portable_and_stable_appid_install_detection(self):
        executable = self.cache / 'Sariana.exe'
        self.assertEqual(installation_kind(frozen=False, executable=executable), 'source')
        self.assertEqual(installation_kind(frozen=True, executable=executable, registry_locations=[]), 'portable')
        self.assertEqual(installation_kind(frozen=True, executable=executable, registry_locations=[self.cache]), 'installed')
        self.assertEqual(installation_kind(frozen=True, executable=executable, registry_locations=[self.cache.parent]), 'portable')

    def test_helper_requires_authorization_after_parent_exit_and_rechecks_package(self):
        if sys.platform != 'win32':
            self.skipTest('Windows helper protocol')
        cache = Path(self.temp.name) / 'update-cache'
        cache.mkdir()
        installer = cache / 'Sariana-1.0.0-windows-x64-setup.exe'
        installer.write_bytes(BODY)
        token = 'a' * 32
        args = SimpleNamespace(data_dir=self.temp.name, run_update_installer=str(installer),
            update_parent_pid=123, update_sha256=DIGEST, update_size=len(BODY), update_authorization=token)
        kernel = Mock()
        kernel.OpenProcess.return_value = 1
        kernel.WaitForSingleObject.return_value = 0
        with patch.object(sys, 'frozen', True, create=True), patch('ctypes.WinDLL', return_value=kernel), \
             patch('app.integrations.updates.service.subprocess.Popen') as spawn:
            with self.assertRaises(RuntimeError):
                run_installer_helper(args)
            spawn.assert_not_called()
            ready = cache / f'authorization-{token}.ready'
            ready.write_text(token)
            installer.write_bytes(b'x' * len(BODY))
            with self.assertRaises(ValueError):
                run_installer_helper(args)
            spawn.assert_not_called()
            self.assertFalse(ready.exists())
            ready.write_text(token)
            installer.write_bytes(BODY)
            self.assertEqual(run_installer_helper(args), 0)
            spawn.assert_called_once_with([str(installer)])
            self.assertFalse(ready.exists())

    def test_cancelling_handoff_removes_authorization_and_only_terminates_owned_process(self):
        process = Mock()
        process.poll.return_value = None
        ready = Path(self.temp.name) / 'authorization.ready'
        handoff = InstallerHandoff(process, ready, 'test-token')
        handoff.authorize()
        self.assertEqual(ready.read_text(), 'test-token')
        handoff.cancel()
        self.assertFalse(ready.exists())
        process.terminate.assert_called_once()


class UpdateDesktopTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.local').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.local')
        self.application = DesktopApplication(self.temp.name, BALANCE, {})
        self.service = UpdateService(Path(self.temp.name) / 'updates', '0.9.4',
            opener=FakeOpener({API_URL: json.dumps(payload()[0]).encode()}))

    def tearDown(self):
        self.application.close()
        APP.processEvents()
        self.temp.cleanup()

    def test_automatic_checks_are_daily_and_disabled_setting_is_respected(self):
        controller = UpdateController(self.application, self.service, kind='source', clock=lambda: 100_000)
        try:
            controller.auto_check()
            self.assertTrue(pump_until(lambda: not controller.busy))
            self.assertEqual(len(self.service._opener.requests), 1)
            self.application.worker.submit(lambda _: None).result(5)
            controller.auto_check()
            self.assertEqual(len(self.service._opener.requests), 1)
            self.application.set_settings({'updates_auto_check': '0', 'updates_last_check': '0'}).result(5)
            controller.auto_check()
            self.assertEqual(len(self.service._opener.requests), 1)
            controller.check(manual=True)
            self.assertTrue(pump_until(lambda: not controller.busy))
            self.assertEqual(len(self.service._opener.requests), 2)
            widget = UpdatesWidget(self.application.models, controller)
            self.assertEqual(widget.action.text(), '查看版本信息')
            widget.deleteLater()
        finally:
            controller.shutdown()
            controller.deleteLater()

    def test_settings_write_failure_does_not_cause_hourly_auto_checks(self):
        from concurrent.futures import Future
        now = [100_000]
        controller = UpdateController(self.application, self.service, kind='source', clock=lambda: now[0])
        failed = Future()
        failed.set_exception(OSError('isolated settings write failure'))
        try:
            with patch.object(self.application, 'set_setting', return_value=failed):
                controller.auto_check()
                self.assertTrue(pump_until(lambda: not controller.busy))
                now[0] += 3600
                controller.auto_check()
                self.assertEqual(len(self.service._opener.requests), 1)
                now[0] += 86400
                controller.auto_check()
                self.assertTrue(pump_until(lambda: not controller.busy))
                self.assertEqual(len(self.service._opener.requests), 2)
        finally:
            controller.shutdown()
            controller.deleteLater()

    def test_prepare_drains_accepted_commands_before_checkpoint_and_finish_is_guarded(self):
        with self.assertRaises(RuntimeError):
            self.application.finish_update_exit().result(5)
        entered, release = threading.Event(), threading.Event()
        def accepted(context):
            entered.set()
            release.wait(5)
            context['counter'].handle_char('en')
        pending = self.application._submit(accepted)
        self.assertTrue(entered.wait(5))
        final = self.application.prepare_update_exit()
        self.assertFalse(final.done())
        with self.assertRaises(RuntimeError):
            self.application.set_setting('after_stop', '1').result(5)
        release.set()
        pending.result(5)
        final.result(5)
        saved = self.application.worker.submit(lambda c: c['repo']._conn.execute('SELECT version FROM tracking_checkpoint').fetchone()[0]).result(5)
        self.assertEqual(saved, self.application.counter.snapshot()['version'])
        self.application.finish_update_exit().result(5)
        self.assertTrue(self.application._closed)

    def test_final_commit_failure_never_launches_installer_worker_and_dirty_state_survive(self):
        self.application.counter.handle_char('en')
        launched, completed, failures = [], [], []
        coordinator = UpdateExitCoordinator(self.application, lambda: None,
            lambda _: launched.append(True), lambda: completed.append(True), failures.append)
        from app.workflows.checkpoint import CheckpointWriter
        with patch.object(CheckpointWriter, 'save', side_effect=OSError('isolated disk failure')):
            coordinator.begin(object())
            self.assertTrue(pump_until(lambda: bool(failures)))
        self.assertEqual(launched, [])
        self.assertEqual(completed, [])
        self.assertFalse(self.application._closed)
        self.assertIsNotNone(self.application.counter.prepare_checkpoint())
        self.application.set_setting('still_alive', 'yes').result(5)
        self.assertEqual(self.application.models.get_setting('still_alive'), 'yes')
        coordinator.begin(object())
        self.assertTrue(pump_until(lambda: bool(completed)))
        self.assertEqual(launched, [True])
        self.assertTrue(self.application._closed)
        coordinator.deleteLater()

    def test_close_failure_cancels_helper_without_authorization(self):
        from concurrent.futures import Future
        failed_close = Future()
        failed_close.set_exception(OSError('isolated close failure'))
        helper = Mock()
        cancelled = threading.Event()
        helper.cancel.side_effect = cancelled.set
        failures = []
        coordinator = UpdateExitCoordinator(self.application, lambda: None,
            lambda _: helper, lambda: self.fail('must not complete'), failures.append)
        with patch.object(self.application, 'finish_update_exit', return_value=failed_close):
            coordinator.begin(object())
            self.assertTrue(pump_until(lambda: bool(failures) and cancelled.is_set()))
        helper.authorize.assert_not_called()
        helper.cancel.assert_called_once()
        self.application.set_setting('after_close_failure', 'alive').result(5)
        coordinator.deleteLater()

    def test_success_authorizes_helper_only_after_worker_closed(self):
        events = []
        helper = Mock()
        def authorize():
            self.assertTrue(self.application._closed)
            events.append('authorized')
        helper.authorize.side_effect = authorize
        coordinator = UpdateExitCoordinator(self.application, lambda: None,
            lambda _: helper, lambda: events.append('complete'), lambda error: self.fail(str(error)))
        coordinator.begin(object())
        self.assertTrue(pump_until(lambda: 'complete' in events))
        self.assertEqual(events, ['authorized', 'complete'])
        helper.cancel.assert_not_called()
        coordinator.deleteLater()

    def test_authorization_failure_after_close_cancels_helper_and_reports_closed_state(self):
        helper = Mock()
        helper.authorize.side_effect = OSError('isolated authorization write failure')
        cancelled = threading.Event()
        helper.cancel.side_effect = cancelled.set
        closed_state = []
        coordinator = UpdateExitCoordinator(self.application, lambda: None,
            lambda _: helper, lambda: self.fail('must not install'),
            lambda error: closed_state.append(self.application._closed))
        coordinator.begin(object())
        self.assertTrue(pump_until(lambda: bool(closed_state) and cancelled.is_set()))
        self.assertEqual(closed_state, [True])
        helper.cancel.assert_called_once()
        coordinator.deleteLater()


if __name__ == '__main__':
    unittest.main()
