"""Filesystem recovery and untrusted archive checks; no actual service calls."""
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
import hashlib
import importlib.util
import json
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release', ROOT/'deploy/krsaangi_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = self.root/'app'
        self.app.mkdir()
        (self.app/'.venv').mkdir()
        (self.app/'.venv/environment-marker').write_text('installed packages')
        (self.app/'app.py').write_text('VERSION = "old"\n')
        for name in ['requirements.txt', 'requirements-hosted.txt']:
            (self.app/name).write_text('same requirements\n')
        self.uploads = self.root/'uploads'
        self.uploads.mkdir()
        (self.uploads/'user.mp4').write_bytes(b'user upload must survive')
        self.stage = self.root/'stage'
        self.stage.mkdir()
        (self.stage/'app.py').write_text('VERSION = "new"\n')
        self.backups = self.root/'backups'
        self.calls = []

    def activate(self, health):
        return release.activate(self.stage, self.app, self.backups,
                                control=self.calls.append, health=health)

    def test_success_preserves_environment_uploads_and_old_code(self):
        backup = self.activate(lambda: True)
        self.assertIn('new', (self.app/'app.py').read_text())
        self.assertIn('old', (self.backups/backup/'app/app.py').read_text())
        self.assertEqual((self.app/'.venv/environment-marker').read_text(), 'installed packages')
        self.assertFalse((self.backups/backup/'app/.venv').exists())
        self.assertEqual((self.uploads/'user.mp4').read_bytes(), b'user upload must survive')
        self.assertEqual(self.calls, ['stop', 'start'])

    def test_failed_startup_restores_old_code_and_environment(self):
        outcomes = iter([False, True])
        with self.assertRaisesRegex(RuntimeError, 'previous application restored'):
            self.activate(lambda: next(outcomes))
        self.assertIn('old', (self.app/'app.py').read_text())
        self.assertEqual((self.app/'.venv/environment-marker').read_text(), 'installed packages')
        self.assertEqual((self.uploads/'user.mp4').read_bytes(), b'user upload must survive')
        failed = next(self.backups.glob('failed-*'))
        self.assertIn('new', (failed/'app.py').read_text())
        self.assertEqual(self.calls, ['stop', 'start', 'stop', 'start'])

    def archive(self, requirements=b'same requirements\n', extra=None):
        files = {name: b'pass\n' if name.endswith('.py') else b'model or license'
                 for name in ['app.py', 'analyzer.py', 'quick_screen.py', 'LICENSE', 'yolov8n-seg.pt', 'obstruction-world.pt']}
        files['requirements.txt'] = requirements
        files['requirements-hosted.txt'] = b'same requirements\n'
        if extra:
            files.update(extra)
        manifest = {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in files.items()}
        path = self.root/'release.zip'
        with ZipFile(path, 'w') as z:
            for name, data in files.items():
                z.writestr(name, data)
            z.writestr('BUILD_MANIFEST.json', json.dumps(manifest))
            z.writestr('RELEASE.json', json.dumps({'commit': 'a'*40, 'clip_acceptance_checked': True}))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_valid_archive_is_checked_without_running_candidate_code(self):
        path, sha = self.archive(extra={'not_imported.py': b'raise RuntimeError("must not execute")\n'})
        with patch.object(release, 'APP', self.app):
            self.assertEqual(release.check_archive(path, sha)['commit'], 'a'*40)

    def test_changed_dependencies_rejected_before_service_changes(self):
        path, sha = self.archive(requirements=b'new dependencies\n')
        with patch.object(release, 'APP', self.app), self.assertRaisesRegex(ValueError, 'Dependency files changed'):
            release.check_archive(path, sha)
        self.assertEqual(self.calls, [])

    def test_path_traversal_and_environment_overwrite_rejected(self):
        for name in ['../escape.py', '.venv/bin/python', '/absolute.py', 'a/./b.py']:
            path, sha = self.archive(extra={name: b'pass\n'})
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Unsafe release member'):
                release.check_archive(path, sha)
        self.assertFalse((self.root.parent/'escape.py').exists())

    def test_upload_checksum_mismatch_rejected(self):
        path, _ = self.archive()
        with self.assertRaisesRegex(ValueError, 'checksum differs'):
            release.check_archive(path, '0'*64)


if __name__ == '__main__':
    unittest.main()
