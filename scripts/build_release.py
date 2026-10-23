"""Build versioned Windows assets from an explicit, clean source snapshot."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import marshal
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import CodeType
import zipfile

TOOLS_ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    """流式计算文件的 SHA-256 摘要，用于发布清单与附件校验。"""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run_logged(command: list[str], log_path: Path, cwd: Path | None = None) -> None:
    """Keep a local log and stream diagnostics to CI instead of hiding build progress."""
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end='', flush=True)
        returncode = process.wait()
        if returncode:
            raise subprocess.CalledProcessError(returncode, command)


def read_version(source: Path) -> str:
    """静态读取源码包的数字版本号，不导入应用或执行启动逻辑；格式不合法时拒绝构建。"""
    tree = ast.parse((source / 'app/__init__.py').read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r'\d+\.\d+\.\d+', value):
                return value
    raise ValueError('app/__init__.py must define a numeric __version__')


def read_brand(source: Path) -> str:
    """Historical tags keep their filenames when built by current tooling."""
    tree = ast.parse((source / 'app/__init__.py').read_text(encoding='utf-8-sig'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == 'APP_NAME' for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,40}', value):
                return value
            raise ValueError('APP_NAME must be a safe ASCII product identifier')
    return 'TypingTracker'


def normalize(code: CodeType) -> CodeType:
    """递归统一代码对象的文件名，使不同源码路径下的冻结代码可以比较。"""
    return code.replace(co_filename='checked.py', co_consts=tuple(
        normalize(value) if isinstance(value, CodeType) else value for value in code.co_consts))


def runtime_files(source: Path) -> list[Path]:
    """列出数据库建表脚本、配置、主题与界面素材，排除字节码和临时文件。"""
    files = [source / 'app/storage/schema.sql']
    for directory in ('config', 'app/theme/themes', 'app/ui/assets'):
        files.extend(path for path in (source / directory).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts
                     and path.suffix not in ('.pyc', '.pyo', '.tmpc'))
    return files


def check_bootstrap(command: list[str], timeout: float = 60) -> None:
    """Bound the complete frozen process tree, without inherited PIPE handles."""
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if sys.platform == 'win32':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        else:
            process.kill()
        process.wait(timeout=10)
        raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)


def news_runtime_modules(source: Path) -> list[str]:
    """按源码存在性校验来信及故障状态模块，缺少后来新增文件的历史标签保持兼容。"""
    if not (source / 'app/modules/companion/news.py').is_file():
        return []
    modules = ['app.modules.companion.' + name for name in
            ('news', 'news_codec', 'memory', 'news_service', 'repository')] + [
        'app.workflows.companion_news', 'app.integrations.development_index',
        'app.ui.companion.news_controller', 'app.ui.companion.news_settings',
        'app.ui.companion.memory_presenter', 'app.ui.companion.memory_page']
    modules.extend('app.modules.companion.' + name for name in ('failures', 'news_status')
                   if (source / ('app/modules/companion/' + name + '.py')).is_file())
    return modules


def verify_executable(exe: Path, source: Path) -> dict:
    """比对冻结程序代码及素材并运行无网自检，按源码存在性核准来信模块清单。"""
    from PyInstaller.archive.readers import CArchiveReader

    check_bootstrap([str(exe), '--help'])
    if (source / 'app/integrations/companion_agent/probe.py').is_file():
        check_bootstrap([str(exe), '--companion-agent-selfcheck'])
    archive = CArchiveReader(str(exe))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith('.pyz')))
    checked = []
    for module in pyz.toc:
        if module == 'app' or module.startswith('app.'):
            relative = module.replace('.', '/')
            path = source / (relative + '.py')
            if not path.is_file():
                path = source / relative / '__init__.py'
            if not path.is_file():
                raise ValueError(f'Unexpected packaged app module: {module}')
            if normalize(pyz.extract(module)) != normalize(compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)):
                raise ValueError(f'Packaged code differs from source: {module}')
            checked.append(module)
    required_modules = ['app','app.ui.main_window','app.ui.settings_dialog']
    required_modules.extend(news_runtime_modules(source))
    if (source / 'app/bootstrap/application.py').is_file():
        required_modules.extend(('app.integrations.ai.service','app.bootstrap.application',
                                 'app.modules.tracking.domain','app.modules.growth.settlement'))
        if (source / 'app/integrations/updates/service.py').is_file():
            required_modules.extend(('app.integrations.updates.service','app.ui.updates',
                                     'app.modules.english.review'))
        if (source / 'app/integrations/companion_agent/service.py').is_file():
            required_modules.extend(('app.integrations.companion_agent.service',
                                     'app.integrations.companion_agent.graph',
                                     'app.integrations.companion_agent.stream',
                                     'app.integrations.companion_agent.edge_search',
                                     'app.integrations.companion_agent.pages',
                                     'app.ui.companion.agent_controller'))
            if (source / 'app/integrations/companion_agent/setup.py').is_file():
                required_modules.extend(('app.integrations.companion_agent.setup',
                                         'app.integrations.companion_agent.search'))
            if 'langgraph.graph.state' not in pyz.toc:
                raise ValueError('Missing packaged LangGraph runtime')
    else:
        required_modules.append('app.services.ai_service')
    for required in required_modules:
        if required not in checked:
            raise ValueError(f'Missing packaged module: {required}')
    main = source / 'main.py'
    if normalize(marshal.loads(archive.extract('main'))) != normalize(compile(main.read_bytes(), str(main), 'exec', dont_inherit=True)):
        raise ValueError('Packaged main differs from source')
    packed = {name.replace('\\', '/'): name for name in archive.toc}
    if any('__pycache__' in name.split('/') or name.endswith('.tmpc') for name in packed):
        raise ValueError('Build caches must not be packaged as runtime data')
    assets = runtime_files(source)
    for path in assets:
        name = path.relative_to(source).as_posix()
        if name not in packed or archive.extract(packed[name]) != path.read_bytes():
            raise ValueError(f'Missing or changed runtime asset: {name}')
    return {'bootstrap_exit': 0, 'source_modules_verified': len(checked) + 1,
            'runtime_assets_verified': len(assets), 'exe_sha256': sha256(exe)}


def build_executable(source: Path, output: Path, version: str) -> Path:
    """在指定输出目录生成版本资源与 PyInstaller 配置，打包应用及 Qt/智能体依赖；构建失败由日志执行器报错。"""
    import PySide6

    brand = read_brand(source)
    build = output / 'build'
    build.mkdir()
    qt_root = Path(PySide6.__file__).parent
    vc_dlls = [(str(path), '.') for path in qt_root.glob('*140*.dll')]
    if not vc_dlls:
        raise ValueError('Qt runtime VC DLLs not found')
    version_file = build / 'version.txt'
    version_tuple = tuple(int(part) for part in version.split('.')) + (0,)
    version_file.write_text(
        "VSVersionInfo(ffi=FixedFileInfo(filevers=" + repr(version_tuple) +
        ", prodvers=" + repr(version_tuple) +
        ", mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0,0)), "
        "kids=[StringFileInfo([StringTable('040904B0', ["
        "StringStruct('CompanyName', 'JeropsWang'),"
        f"StringStruct('ProductName', '{brand}'),"
        f"StringStruct('FileVersion', '{version}'),StringStruct('ProductVersion', '{version}'),"
        f"StringStruct('FileDescription', '{brand}'),"
        f"StringStruct('OriginalFilename', '{brand}.exe')])]),"
        "VarFileInfo([VarStruct('Translation', [1033, 1200])])])", encoding='utf-8')
    datas = [(str(path), path.parent.relative_to(source).as_posix()) for path in runtime_files(source)]
    spec = build / f'{brand}.spec'
    agent_support = (source / 'app/integrations/companion_agent/service.py').is_file()
    spec.write_text(
        "from PyInstaller.utils.hooks import collect_submodules, copy_metadata\n" +
        ("agent_hidden = collect_submodules('langgraph')\n"
         "agent_metadata = copy_metadata('langgraph', recursive=True)\n" if agent_support else
         "agent_hidden = []\nagent_metadata = []\n") +
        f"a = Analysis([{str(source / 'main.py')!r}], pathex=[{str(source)!r}], "
        f"binaries={vc_dlls!r}, datas={datas!r} + agent_metadata, hiddenimports=agent_hidden, "
        f"runtime_hooks=[{str(source / 'scripts/pyinstaller_runtime.py')!r}], "
        "excludes=['pygame'], optimize=0)\npyz = PYZ(a.pure)\n"
        # Embedded Python ignores PYTHONIOENCODING; UTF-8 must be a bootloader option.
        f"exe = EXE(pyz, a.scripts, a.binaries, a.datas, [('X utf8', None, 'OPTION')], name={brand!r}, "
        f"console=False, upx=False, icon={str(source / 'app.ico')!r}, version={str(version_file)!r})\n",
        encoding='utf-8')
    run_logged([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                '--distpath', str(output / 'payload'), '--workpath', str(build / 'work'), str(spec)],
               output / 'build.log', cwd=source)
    return output / f'payload/{brand}.exe'


def main() -> None:
    """校验源码版本与输出目录后构建或核验现有 exe，生成安装包、发布清单和校验和；调用 PyInstaller 与 Inno Setup，不发布附件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--expected-version')
    parser.add_argument('--iscc', type=Path, required=True)
    parser.add_argument('--existing-exe', type=Path, help='Repackage only after verifying this executable against the source snapshot')
    args = parser.parse_args()
    source, output, iscc = args.source_dir.resolve(), args.output_dir.resolve(), args.iscc.resolve()
    version = read_version(source)
    brand = read_brand(source)
    if args.expected_version and args.expected_version != version:
        parser.error(f'Tag version {args.expected_version} differs from source version {version}')
    if not re.fullmatch(r'[0-9a-f]{40}', args.source_commit):
        parser.error('--source-commit must be a full Git commit SHA')
    if not iscc.is_file():
        parser.error('Inno Setup ISCC.exe not found')
    if output.exists() and any(output.iterdir()):
        parser.error('Use an empty output directory; existing packages are never overwritten')
    if output == source or source in output.parents:
        parser.error('Keep build outputs outside the source snapshot')
    output.mkdir(parents=True, exist_ok=True)
    print(f'Building {brand} {version} from {args.source_commit}', flush=True)
    if args.existing_exe:
        original_exe = args.existing_exe.resolve()
        verify_executable(original_exe, source)
        (output / 'payload').mkdir()
        exe = output / f'payload/{brand}.exe'
        shutil.copyfile(original_exe, exe)
    else:
        exe = build_executable(source, output, version)
    print('Checking frozen application startup, source code and runtime assets', flush=True)
    verification = verify_executable(exe, source)
    print('Frozen application verified; creating portable ZIP and installer', flush=True)
    payload = exe.parent
    for origin, name in ((source / 'LICENSE', 'LICENSE'),
                         (source / 'config/vocabulary/LICENSE-ECDICT.txt', 'LICENSE-ECDICT.txt'),
                         (source / 'app.ico', 'app.ico')):
        shutil.copyfile(origin, payload / name)
    (payload / 'INSTALL.txt').write_text(
        f'{brand} {version}\nSource commit: {args.source_commit}\n\n'
        '安装版：运行 setup.exe，可在开始菜单启动。\n'
        f'免安装版：解压整个 ZIP，再运行 {brand}.exe。\n'
        '升级前请从托盘退出旧进程。记录保存在 %APPDATA%\\TypingTracker；卸载保留记录。\n',
        encoding='utf-8-sig')
    manifest = dict(product_name=brand, executable=f'{brand}.exe',
                    version=version, source_commit=args.source_commit, platform='windows-x64',
                    python=sys.version.split()[0], **verification)
    (payload / 'release-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    assets = output / 'assets'
    assets.mkdir()
    portable = assets / f'{brand}-{version}-windows-x64-portable.zip'
    with zipfile.ZipFile(portable, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(payload.iterdir()):
            bundle.write(path, f'{brand}-{version}/{path.name}')
    with zipfile.ZipFile(portable) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('Portable ZIP integrity check failed')
        if hashlib.sha256(bundle.read(f'{brand}-{version}/{brand}.exe')).hexdigest() != sha256(exe):
            raise ValueError('Portable executable checksum mismatch')
    run_logged([str(iscc), f'/DAppVersion={version}', f'/DAppBrand={brand}', f'/DPayloadDir={payload}',
                f'/DOutputDir={assets}', str(TOOLS_ROOT / 'packaging/windows/TypingTracker.iss')],
               output / 'installer-build.log')
    setup = assets / f'{brand}-{version}-windows-x64-setup.exe'
    if not setup.is_file():
        raise ValueError('Installer was not created')
    shutil.copyfile(payload / 'release-manifest.json', assets / f'{brand}-{version}-manifest.json')
    checksums = assets / f'{brand}-{version}-SHA256SUMS.txt'
    checksums.write_text(''.join(f'{sha256(path)}  {path.name}\n' for path in sorted(assets.iterdir())), encoding='ascii')
    print(json.dumps(manifest), flush=True)
    for path in sorted(assets.iterdir()):
        print(f'{path.name}: {path.stat().st_size:,} bytes', flush=True)


if __name__ == '__main__':
    main()
