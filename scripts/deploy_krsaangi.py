"""Deploy a reviewed main commit, inspect status, or restore an existing backup."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['deploy', 'status', 'rollback', 'logs'])
    parser.add_argument('--host', default='footpath-deployer@134.209.149.217', help='Restricted SSH account or configured SSH alias')
    parser.add_argument('--identity', type=Path, help='Dedicated deployment SSH private key (or configure IdentityFile in ~/.ssh/config)')
    parser.add_argument('--backup', help='Exact backup ID returned by a prior deployment/status')
    parser.add_argument('--dry-run', action='store_true', help='Upload and validate, without restarting or modifying the service')
    parser.add_argument('--skip-tests', action='store_true', help='Reuse matching clip acceptance already available locally')
    args = parser.parse_args()
    if args.host.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.@:-]+', args.host):
        parser.error('Invalid SSH target')
    ssh = ['ssh', '-T', '-o', 'BatchMode=yes']
    if args.identity:
        identity = args.identity.expanduser().resolve()
        if not identity.is_file():
            parser.error('SSH identity file not found')
        ssh += ['-o', 'IdentitiesOnly=yes', '-i', str(identity)]
    ssh += [args.host]
    remote_args = [args.action]
    uploaded = None
    try:
        if args.action == 'deploy':
            dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
            if dirty:
                parser.error('Commit or discard source changes before deployment; generated artifacts are ignored')
            commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
            remote = subprocess.check_output(['git', 'ls-remote', 'origin', 'refs/heads/main'], cwd=ROOT, text=True).split()
            if not remote or remote[0] != commit:
                parser.error('Deploy the reviewed commit currently pushed to origin/main')
            if not args.skip_tests:
                run([sys.executable, '.video-tools/validate_clips.py', '--mode', 'local'])
            run([sys.executable, 'scripts/build_source.py'])
            archive = ROOT/'dist/source.zip'
            with archive.open('rb') as handle:
                transfer = run(ssh+['upload'], stdin=handle, stdout=subprocess.PIPE, text=True)
            result = json.loads(transfer.stdout)
            uploaded = result['upload']
            sha = hashlib.sha256(archive.read_bytes()).hexdigest()
            if not re.fullmatch('[0-9a-f]{32}', uploaded) or result['sha256'] != sha:
                raise RuntimeError('Upload acknowledgement or checksum is invalid')
            remote_args += [uploaded, sha]
        elif args.action == 'rollback':
            if not args.backup:
                parser.error('Supply --backup from the status command')
            remote_args += [args.backup]
        if args.dry_run:
            remote_args += ['--dry-run']
        # OpenSSH forces the root-owned gateway. Client source is never run
        # with sudo; only the separately installed fixed helper is privileged.
        completed = run(ssh+[shlex.join(remote_args)], text=True, stdout=subprocess.PIPE)
        result = json.loads(completed.stdout)
        print(result['logs'] if args.action == 'logs' else completed.stdout, end='\n' if args.action == 'logs' else '', flush=True)
        if result.get('ok'):
            print('Verified local service health. Now check the public page and run the public clip checks.', flush=True)
    finally:
        if uploaded:
            if re.fullmatch('[0-9a-f]{32}', uploaded):
                subprocess.run(ssh+['discard '+uploaded], cwd=ROOT, stdout=subprocess.DEVNULL, check=False)


if __name__ == '__main__':
    main()
