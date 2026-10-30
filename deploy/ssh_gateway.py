#!/usr/bin/python3 -I
"""Forced SSH command. No shell, SCP, SFTP or user-supplied executable runs."""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import pwd
import re
import shlex
import subprocess
import sys
import time
import uuid

INBOX = Path('/var/lib/pedestrian-shield-deploy/inbox')
UPLOAD_LOCK = Path('/var/lib/pedestrian-shield-deploy/upload.lock')
HELPER = '/usr/local/sbin/pedestrian-shield-release'
MAX_UPLOAD = 256 * 1024**2


def parse_command(command):
    args = shlex.split(command)
    if args in [['upload'], ['status'], ['logs']]:
        return args
    if len(args) == 2 and args[0] == 'discard' and re.fullmatch('[0-9a-f]{32}', args[1]):
        return args
    dry = args[-1:] == ['--dry-run']
    values = args[:-1] if dry else args
    if (len(values) == 3 and values[0] == 'deploy'
            and re.fullmatch('[0-9a-f]{32}', values[1]) and re.fullmatch('[0-9a-f]{64}', values[2])):
        return args
    if len(values) == 2 and values[0] == 'rollback' and re.fullmatch('[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}', values[1]):
        return args
    raise ValueError('Allowed commands: upload, deploy TOKEN SHA [--dry-run], status, logs, rollback ID [--dry-run], discard TOKEN')


def upload():
    for path in INBOX.iterdir():
        if re.fullmatch('[0-9a-f]{32}[.](zip|part)', path.name) and time.time()-path.stat().st_mtime > 3600:
            path.unlink(missing_ok=True)
    if len(list(INBOX.iterdir())) >= 3:
        raise ValueError('Upload queue is full; discard an old upload first')
    token = uuid.uuid4().hex
    partial = INBOX/(token+'.part')
    sha = hashlib.sha256()
    size = 0
    try:
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            while True:
                block = sys.stdin.buffer.read(1024**2)
                if not block:
                    break
                size += len(block)
                if size > MAX_UPLOAD:
                    raise ValueError('Release exceeds 256 MiB upload limit')
                sha.update(block)
                handle.write(block)
        partial.rename(INBOX/(token+'.zip'))
        print(json.dumps({'upload': token, 'sha256': sha.hexdigest(), 'bytes': size}))
    finally:
        partial.unlink(missing_ok=True)


def main():
    if os.getuid() != pwd.getpwnam('footpath-deployer').pw_uid:
        raise ValueError('This gateway belongs to the footpath-deployer account')
    args = parse_command(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    if args[0] == 'upload':
        with UPLOAD_LOCK.open('r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            upload()
        return
    if args[0] == 'discard':
        (INBOX/(args[1]+'.zip')).unlink(missing_ok=True)
        print(json.dumps({'discarded': True}))
        return
    command = ['/usr/bin/sudo', '-n', HELPER, args[0]]
    if args[0] == 'deploy':
        command += ['--upload', args[1], '--sha256', args[2]]
    elif args[0] == 'rollback':
        command += ['--backup', args[1]]
    if args[-1:] == ['--dry-run']:
        command += ['--dry-run']
    subprocess.run(command, check=True, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'})


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        sys.exit(2)
