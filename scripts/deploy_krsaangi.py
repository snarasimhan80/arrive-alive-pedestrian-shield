"""Deploy a reviewed main commit, inspect status, or restore an existing backup."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['deploy', 'status', 'rollback'])
    parser.add_argument('--host', required=True, help='Your own SSH account or configured SSH alias')
    parser.add_argument('--backup', help='Exact backup ID returned by a prior deployment/status')
    parser.add_argument('--dry-run', action='store_true', help='Upload and validate, without restarting or modifying the service')
    parser.add_argument('--skip-tests', action='store_true', help='Reuse matching clip acceptance already available locally')
    args = parser.parse_args()
    if args.host.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.@:-]+', args.host):
        parser.error('Invalid SSH target')
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
            uploaded = '/tmp/pedestrian-shield-'+uuid.uuid4().hex+'.zip'
            run(['scp', str(archive), args.host+':'+uploaded])
            remote_args += ['--archive', uploaded, '--sha256', hashlib.sha256(archive.read_bytes()).hexdigest()]
        elif args.action == 'rollback':
            if not args.backup:
                parser.error('Supply --backup from the status command')
            remote_args += ['--backup', args.backup]
        if args.dry_run:
            remote_args += ['--dry-run']
        # The server helper is sent from the reviewed checkout. This requires
        # an administrator's SSH access; the repository itself grants none.
        command = 'sudo -n python3 - '+shlex.join(remote_args)
        completed = run(['ssh', args.host, command], input=(ROOT/'deploy/krsaangi_release.py').read_text(),
                        text=True, stdout=subprocess.PIPE)
        print(completed.stdout, end='', flush=True)
        result = json.loads(completed.stdout)
        if result.get('ok'):
            print('Verified local service health. Now check the public page and run the public clip checks.', flush=True)
    finally:
        if uploaded:
            subprocess.run(['ssh', args.host, 'rm -f -- '+shlex.quote(uploaded)], cwd=ROOT, check=False)


if __name__ == '__main__':
    main()
