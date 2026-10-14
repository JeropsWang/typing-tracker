"""Verify the shipped updater against public GitHub Releases using isolated cache.

--exe loads the updater code from our verified frozen package. It never starts
the installer. --detect-installation-only is suitable inside installer smoke tests.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
import threading
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_updater(executable=None):
    """加载工作区更新服务或静态提取受信冻结包内代码，返回服务与版本；不启动 exe 或安装器。"""
    if executable is None:
        from app import __version__
        from app.integrations.updates import service
        return service, __version__
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(executable))
    pyz = archive.open_embedded_archive(next(key for key in archive.toc if key.endswith('.pyz')))
    app = {}
    exec(pyz.extract('app'), app)
    name = '_sariana_verified_packaged_updater'
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(pyz.extract('app.integrations.updates.service'), module.__dict__)
    return module, app['__version__']


def verify(*, cache_dir=None, expected_version=None, older_version='0.9.4', executable=None,
           expected_package_version=None, expected_source_commit=None,
           detect_installation_only=False, require_installed=False):
    """验证安装类型、版本选择及下载摘要，可只做安装检测；完整模式访问发布服务并下载到隔离缓存，不执行安装器。"""
    module, package_version = load_updater(executable)
    if expected_package_version and package_version != expected_package_version:
        raise ValueError(f'Package version differs: {package_version}')
    kind = module.installation_kind(frozen=executable is not None, executable=executable)
    report = dict(package_version=package_version, installation_kind=kind,
                  code_source='frozen package' if executable else 'workspace', installer_started=False)
    if require_installed and kind != 'installed':
        raise ValueError(f'Installed executable was identified as {kind}')
    if detect_installation_only:
        return report
    if not cache_dir or not expected_version:
        raise ValueError('Online verification requires cache_dir and expected_version')
    cache_dir = Path(cache_dir).resolve()
    service = module.UpdateService(cache_dir / 'digest', older_version)
    release = service.check()
    if release is None or release.version != expected_version:
        raise ValueError(f'Expected latest {expected_version}, got {release}')
    if not release.installer or not release.portable or not release.checksums:
        raise ValueError('Release is missing required installer/portable/checksum assets')
    installed = service.download(release, threading.Event())
    installed.verify()
    # Exercise the fallback with the real GitHub checksum file, reusing the package
    # bytes already downloaded rather than fetching the same 100+ MB a second time.
    class ReuseDownloadedPackage:
        """校验和回退场景的下载适配器，复用已下载安装包，其他请求交给原网络客户端。"""
        def open(self, request, timeout):
            """安装包 URL 返回本地缓存文件流，其他 URL 沿用原 opener 和超时设置。"""
            if request.full_url == release.installer.url:
                return installed.path.open('rb')
            return service._opener.open(request, timeout=timeout)
    fallback = module.UpdateService(cache_dir / 'checksum-fallback', older_version,
                                    opener=ReuseDownloadedPackage())
    fallback_release = replace(release, installer=replace(release.installer, digest=''))
    fallback_package = fallback.download(fallback_release, threading.Event())
    if fallback_package.digest != installed.digest:
        raise ValueError('GitHub digest and SHA256SUMS disagree')
    base = f'https://github.com/{module.REPOSITORY}/releases/download/v{expected_version}'
    with service._open(f'{base}/Sariana-{expected_version}-manifest.json') as response:
        manifest = json.loads(response.read(2 * 1024 * 1024))
    if manifest['version'] != expected_version or manifest['product_name'] != 'Sariana':
        raise ValueError('Release manifest product/version differs')
    if expected_source_commit and manifest['source_commit'] != expected_source_commit:
        raise ValueError('Release manifest source commit differs')
    current = module.UpdateService(cache_dir / 'current', expected_version)
    if current.check() is not None:
        raise ValueError('Current version unexpectedly offers an update')
    report.update(release=release.url, latest_version=release.version,
                  older_version_detected=True, current_version_ignored=True,
                  installer_path=str(installed.path), installer_size=installed.size,
                  installer_sha256=installed.digest, github_digest_verified=bool(release.installer.digest),
                  github_checksum_fallback_verified=True, source_commit=manifest['source_commit'])
    return report


def main():
    """解析冻结包、版本和缓存参数，执行只读更新验证并输出或保存 JSON 报告。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--expected-version')
    parser.add_argument('--expected-package-version')
    parser.add_argument('--expected-source-commit')
    parser.add_argument('--older-version', default='0.9.4')
    parser.add_argument('--cache-dir', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--detect-installation-only', action='store_true')
    parser.add_argument('--require-installed', action='store_true')
    args = parser.parse_args()
    report = verify(cache_dir=args.cache_dir, expected_version=args.expected_version,
        older_version=args.older_version, executable=args.exe,
        expected_package_version=args.expected_package_version,
        expected_source_commit=args.expected_source_commit,
        detect_installation_only=args.detect_installation_only, require_installed=args.require_installed)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + '\n', encoding='utf-8')
    print(encoded)


if __name__ == '__main__':
    main()
