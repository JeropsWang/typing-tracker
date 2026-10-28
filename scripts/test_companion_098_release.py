"""0.9.8冻结清单和无网络自检回归，不构建或安装正式发布包。"""
from pathlib import Path
import tempfile
import unittest
from app.integrations.companion_agent.probe import selfcheck
from build_release import companion_098_runtime_modules, runtime_files


class Companion098ReleaseTests(unittest.TestCase):
    """旧源码保持兼容，0.9.8仅交付占卜，发布包排除本地模型实验。"""
    def test_historical_sources_do_not_require_098_modules(self):
        """按源码存在性选择新增冻结模块，保证旧标签仍可用当前工具补编。"""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.local') as directory:
            source = Path(directory)
            self.assertEqual(companion_098_runtime_modules(source), [])
            path = source/'app/modules/companion/oracle.py'
            path.parent.mkdir(parents=True)
            path.write_text('"""fixture"""', encoding='utf-8')
            required = companion_098_runtime_modules(source)
            self.assertIn('app.ui.companion.oracle_controller', required)
            self.assertNotIn('app.integrations.companion_render.worker', required)
            render = source/'app/integrations/companion_render/worker.py'
            render.parent.mkdir(parents=True)
            render.write_text('"""fixture"""', encoding='utf-8')
            self.assertNotIn('app.integrations.companion_render.worker', companion_098_runtime_modules(source))

    def test_oracle_selfcheck_without_renderer_or_database(self):
        """占卜自检不再加载渲染器、模型资产或数据库。"""
        result = selfcheck()
        self.assertTrue(result['oracle'])
        self.assertNotIn('render_assets', result)
        self.assertNotIn('render_gpu', result)
        self.assertFalse(result['database'])
        self.assertFalse(result['network'])

    def test_local_model_files_never_enter_runtime_resources(self):
        """即使隔离源码目录混入本地模型，也不能被资源扫描收进冻结包。"""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'.local') as directory:
            source = Path(directory)
            for name in ('app/ui/assets/companion3d/model.bam', 'app/ui/assets/preview.blend',
                         'app/ui/assets/preview.glb', 'app/ui/assets/avatars/front.png'):
                path = source/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            resources = [p.relative_to(source).as_posix() for p in runtime_files(source)]
            self.assertIn('app/ui/assets/avatars/front.png', resources)
            self.assertFalse(any('companion3d' in p or p.endswith(('.blend', '.glb', '.bam')) for p in resources))


if __name__ == '__main__':
    unittest.main()
