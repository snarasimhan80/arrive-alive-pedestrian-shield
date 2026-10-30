"""Enforce the restricted SSH grammar and stable private upload snapshot."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import importlib.util
import os
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'deploy'/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gateway = load('ssh_gateway')
release = load('krsaangi_release')
builder_spec = importlib.util.spec_from_file_location('builder', ROOT/'scripts/build_source.py')
builder = importlib.util.module_from_spec(builder_spec)
builder_spec.loader.exec_module(builder)


class CredentialPublicationTests(unittest.TestCase):
    def test_handover_credentials_never_enter_source_archives(self):
        for name in ['krsaangi-footpath-deployer', 'krsaangi-footpath-deployer.pub',
                     'Pedestrian-Shield-Deployment-Access.zip', 'secret.pem', '.env']:
            with self.subTest(name=name):
                self.assertFalse(builder.include(ROOT/'nested'/name))


class GatewayTests(unittest.TestCase):
    def test_allowed_operations(self):
        for command in ['upload', 'status', 'logs', 'discard '+'a'*32,
                        'deploy '+'a'*32+' '+'b'*64,
                        'deploy '+'a'*32+' '+'b'*64+' --dry-run',
                        'rollback 20261030T104920Z-54a336e1 --dry-run']:
            with self.subTest(command=command):
                self.assertEqual(gateway.parse_command(command), command.split())

    def test_shell_sudo_subsystems_and_injection_denied(self):
        for command in ['', 'sh', 'bash -i', 'id', 'sudo -n id', 'python3 -c pass',
                        'status; id', 'status && id', 'logs --unit ssh.service',
                        'scp -t /tmp', '/usr/lib/openssh/sftp-server',
                        'deploy /etc/shadow '+ 'b'*64,
                        'rollback ../../root', 'discard ../../root',
                        'deploy '+'a'*32+' '+'b'*64+' --archive /etc/shadow']:
            with self.subTest(command=command), self.assertRaises(ValueError):
                gateway.parse_command(command)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.inbox = Path(temp.name)/'inbox'
        self.private = Path(temp.name)/'private'
        self.inbox.mkdir()
        self.private.mkdir(mode=0o700)
        self.token = 'a'*32
        self.source = self.inbox/(self.token+'.zip')
        self.source.write_bytes(b'validated bytes')
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        for attribute, value in [('INBOX', self.inbox), ('PRIVATE', self.private)]:
            changer = patch.object(release, attribute, value)
            changer.start()
            self.addCleanup(changer.stop)
        changer = patch.object(release.pwd, 'getpwnam', return_value=SimpleNamespace(pw_uid=os.getuid()))
        changer.start()
        self.addCleanup(changer.stop)

    def test_existing_writer_cannot_mutate_checked_snapshot(self):
        with self.source.open('r+b') as writer:
            with release.snapshot_upload(self.token, self.sha) as snapshot:
                writer.write(b'changed content')
                writer.flush()
                self.assertEqual(snapshot.read_bytes(), b'validated bytes')
                self.assertFalse(self.source.exists())
                self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
            self.assertFalse(snapshot.exists())

    def test_symlink_is_not_followed(self):
        target = self.inbox/'target'
        self.source.rename(target)
        self.source.symlink_to(target)
        with self.assertRaises(OSError):
            with release.snapshot_upload(self.token, self.sha):
                self.fail('Symlink must not be accepted')

    def test_bad_token_and_checksum_denied(self):
        with self.assertRaises(ValueError):
            with release.snapshot_upload('../../etc/shadow', self.sha):
                self.fail('Traversal must not be accepted')
        with self.assertRaisesRegex(ValueError, 'checksum differs'):
            with release.snapshot_upload(self.token, '0'*64):
                self.fail('Bad checksum must not be accepted')

    def test_oversized_upload_denied(self):
        with patch.object(release, 'MAX_UPLOAD', 3), self.assertRaisesRegex(ValueError, 'bounded regular file'):
            with release.snapshot_upload(self.token, self.sha):
                self.fail('Oversized upload must not be accepted')


if __name__ == '__main__':
    unittest.main()
