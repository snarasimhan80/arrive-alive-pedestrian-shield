#!/usr/bin/python3 -I
"""Root-owned, fixed-purpose release operations for the Krsaangi demo.

Installed outside the app by its owner. Never execute an uploaded helper.
Uploaded footage, the Python environment, Nginx and other apps are preserved.
"""
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import argparse
import ast
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
import uuid

APP = Path('/opt/arrive-alive-module3')
BACKUPS = Path('/opt/arrive-alive-module3-backups')
SERVICE = 'arrive-alive-module3.service'
HEALTH = 'http://127.0.0.1:8765/health'
PROTECTED = {'.venv', 'venv', 'jobs', '.git', '__pycache__'}
INBOX = Path('/var/lib/pedestrian-shield-deploy/inbox')
PRIVATE = Path('/var/lib/pedestrian-shield-deploy/private')
MAX_UPLOAD = 256 * 1024**2
MAX_UNPACKED = 512 * 1024**2
MAX_MEMBER = 64 * 1024**2
MAX_BACKUPS = 10
CLEAN_ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'}


def file_sha(path):
    sha = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024**2), b''):
            sha.update(block)
    return sha.hexdigest()


@contextlib.contextmanager
def snapshot_upload(token, expected_sha):
    """Copy once into root-only storage before checking or extracting bytes."""
    if not re.fullmatch('[0-9a-f]{32}', token or '') or not re.fullmatch('[0-9a-f]{64}', expected_sha or ''):
        raise ValueError('Invalid upload token or SHA-256')
    source = INBOX/(token+'.zip')
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != pwd.getpwnam('footpath-deployer').pw_uid
                or info.st_size > MAX_UPLOAD):
            raise ValueError('Upload must be a bounded regular file owned by the deployment account')
        with tempfile.TemporaryDirectory(prefix='checked-', dir=PRIVATE) as folder:
            target = Path(folder)/'source.zip'
            size = 0
            with target.open('xb') as output:
                for block in iter(lambda: handle.read(1024**2), b''):
                    size += len(block)
                    if size > MAX_UPLOAD:
                        raise ValueError('Upload exceeds size limit')
                    output.write(block)
            target.chmod(0o600)
            if file_sha(target) != expected_sha:
                raise ValueError('Uploaded ZIP checksum differs from the local release')
            source.unlink(missing_ok=True)
            yield target


def check_archive(archive, expected_sha):
    if file_sha(archive) != expected_sha:
        raise ValueError('Uploaded ZIP checksum differs from the local release')
    with ZipFile(archive) as z:
        names = z.namelist()
        if len(names) > 2000 or len(names) != len(set(names)) or sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
            raise ValueError('Duplicate entries or oversized release')
        for item in z.infolist():
            if item.is_dir() or item.file_size > MAX_MEMBER or (item.filename.endswith('.py') and item.file_size > 1024**2):
                raise ValueError('Oversized or non-file release member: '+item.filename)
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or '..' in path.parts or not path.parts or path.as_posix() != item.filename
                    or any(part in PROTECTED for part in path.parts)
                    or '\\' in item.filename or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('Unsafe release member: '+item.filename)
        if z.getinfo('BUILD_MANIFEST.json').file_size > 2 * 1024**2 or z.getinfo('RELEASE.json').file_size > 32768:
            raise ValueError('Oversized release metadata')
        manifest = json.loads(z.read('BUILD_MANIFEST.json'))
        release = json.loads(z.read('RELEASE.json'))
        if set(names) != set(manifest) | {'BUILD_MANIFEST.json', 'RELEASE.json'}:
            raise ValueError('Release inventory does not match its manifest')
        if not re.fullmatch('[0-9a-f]{40}', release.get('commit', '')) or not release.get('clip_acceptance_checked'):
            raise ValueError('Deploy a validated Git commit, not an unvalidated Docker snapshot')
        required = {'app.py', 'analyzer.py', 'quick_screen.py', 'LICENSE',
                    'requirements.txt', 'requirements-hosted.txt',
                    'yolov8n-seg.pt', 'obstruction-world.pt'}
        if not required <= set(manifest):
            raise ValueError('Required application files are missing')
        for name, record in manifest.items():
            data = z.read(name)
            if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
                raise ValueError('Corrupt member: '+name)
            if name.endswith('.py'):
                ast.parse(data, filename=name)
        for name in ['requirements.txt', 'requirements-hosted.txt']:
            if z.read(name) != (APP/name).read_bytes():
                raise ValueError('Dependency files changed. Follow docs/DEPLOYMENT.md dependency maintenance before deploying.')
        return release


def service(action):
    if action not in {'stop', 'start'}:
        raise ValueError('Unsupported service operation')
    subprocess.run(['/usr/bin/systemctl', action, SERVICE], check=True, capture_output=True, text=True, env=CLEAN_ENV)


def healthy():
    for _ in range(40):
        try:
            with urllib.request.urlopen(HEALTH, timeout=2) as response:
                if json.load(response).get('ok'):
                    return True
        except Exception:
            pass
        time.sleep(.5)
    return False


def ensure_idle():
    """Best-effort check of the current worker's queued/running analyses."""
    for folder in Path('/var/lib/arrive-alive-module3/jobs').glob('*'):
        if not re.fullmatch('[0-9a-f]{32}', folder.name):
            continue
        try:
            url = 'http://127.0.0.1:8765/api/status/'+folder.name
            with urllib.request.urlopen(url, timeout=3) as response:
                state = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        if state.get('status') in {'queued', 'running'}:
            raise RuntimeError('An analysis is queued/running; wait for it to finish before deploying')


def activate(stage, app, backups, control=service, health=healthy):
    """Swap complete code trees and retain the installed venv. Restore on failure."""
    if app.is_symlink() or not (app/'.venv').is_dir():
        raise ValueError('Expected the existing app directory and its Python environment')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    backup = backups/stamp
    backup.mkdir(parents=True, exist_ok=False)
    previous = backup/'app'
    moved_old = moved_env = installed = False
    try:
        control('stop')
        app.rename(previous)
        moved_old = True
        (previous/'.venv').rename(stage/'.venv')
        moved_env = True
        stage.rename(app)
        installed = True
        control('start')
        if not health():
            raise RuntimeError('New release failed the local health check')
    except Exception as original:
        control('stop')
        failed = backups/('failed-'+stamp)
        if installed:
            app.rename(failed)
            (failed/'.venv').rename(previous/'.venv')
        elif moved_env:
            (stage/'.venv').rename(previous/'.venv')
        if moved_old:
            previous.rename(app)
        control('start')
        if not health():
            raise RuntimeError('Deployment AND automatic restore failed; inspect '+str(backups)) from original
        raise RuntimeError('Deployment failed; previous application restored: '+str(original)) from original
    return stamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['deploy', 'rollback', 'status', 'logs'])
    parser.add_argument('--upload')
    parser.add_argument('--sha256')
    parser.add_argument('--backup')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Invoke the installed helper through the restricted demo gateway')
    with open('/run/lock/arrive-alive-module3-deploy.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'status':
            current = APP/'RELEASE.json'
            print(json.dumps({'protocol': 2, 'deploy_user': 'footpath-deployer',
                              'release': json.loads(current.read_text()) if current.exists() else 'legacy release',
                              'backups': sorted(p.name for p in BACKUPS.glob('*') if (p/'app').is_dir())}))
            return
        if args.action == 'logs':
            logs = subprocess.check_output(['/usr/bin/journalctl', '-u', SERVICE, '-n', '200', '--no-pager', '--output=cat'], text=True, env=CLEAN_ENV)
            print(json.dumps({'logs': logs}))
            return
        if shutil.disk_usage('/opt').free < 8 * 1024**3:
            raise RuntimeError('Less than 8 GiB free. Ask the server owner to maintain storage before deploying.')
        if BACKUPS.exists() and len(list(BACKUPS.iterdir())) >= MAX_BACKUPS:
            raise RuntimeError('Backup limit reached. Ask the server owner to archive or prune old backups.')
        stage = Path(tempfile.mkdtemp(prefix='arrive-alive-stage-', dir='/opt'))
        os.chmod(stage, 0o755)
        try:
            if args.action == 'deploy':
                with snapshot_upload(args.upload, args.sha256) as archive:
                    release = check_archive(archive, args.sha256)
                    with ZipFile(archive) as z:
                        z.extractall(stage)
                    shutil.copyfile(archive, stage/'source.zip')
            else:
                if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}', args.backup or ''):
                    parser.error('Supply an exact backup ID from the status command')
                previous = BACKUPS/args.backup/'app'
                if not (previous/'app.py').is_file():
                    parser.error('Backup not found')
                for name in ['requirements.txt', 'requirements-hosted.txt']:
                    if (previous/name).read_bytes() != (APP/name).read_bytes():
                        parser.error('Dependency versions differ; use the dependency maintenance procedure')
                shutil.copytree(previous, stage, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.venv', 'jobs', '__pycache__'))
                metadata = stage/'RELEASE.json'
                release = json.loads(metadata.read_text()) if metadata.exists() else {'commit': 'legacy release'}
            for path in stage.rglob('*'):
                path.chmod(0o755 if path.is_dir() else 0o644)
            if args.dry_run:
                print(json.dumps({'dry_run': True, 'release': release, 'service_changed': False}))
                return
            if not healthy():
                raise RuntimeError('Current service is unhealthy; investigate before changing it')
            ensure_idle()
            backup = activate(stage, APP, BACKUPS)
            print(json.dumps({'ok': True, 'release': release, 'backup': backup}))
        finally:
            if stage.exists():
                shutil.rmtree(stage)


if __name__ == '__main__':
    main()
