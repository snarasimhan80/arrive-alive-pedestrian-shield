#!/usr/bin/python3 -I
"""Owner-only installation of the restricted demo deployment account."""
from pathlib import Path
import argparse
import datetime
import grp
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import uuid

USER = 'footpath-deployer'
HOME = Path('/home')/USER
LIB = Path('/usr/local/libexec/pedestrian-shield')
COMMAND = Path('/usr/local/sbin/pedestrian-shield-release')
STATE = Path('/var/lib/pedestrian-shield-deploy')
KEYS = Path('/etc/ssh/authorized_keys')/USER
SUDO = Path('/etc/sudoers.d/pedestrian-shield')
SSHD = Path('/etc/ssh/sshd_config')
BEGIN = '# BEGIN PEDESTRIAN SHIELD RESTRICTED ACCOUNT'
END = '# END PEDESTRIAN SHIELD RESTRICTED ACCOUNT'
RULE = '''Defaults:footpath-deployer env_reset, !setenv, secure_path="/usr/sbin:/usr/bin:/sbin:/bin"
footpath-deployer ALL=(root) NOPASSWD: NOSETENV: /usr/local/sbin/pedestrian-shield-release *
'''
MATCH = '''Match User footpath-deployer
    AuthenticationMethods publickey
    PubkeyAuthentication yes
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AuthorizedKeysFile /etc/ssh/authorized_keys/footpath-deployer
    ForceCommand /usr/local/libexec/pedestrian-shield/ssh_gateway.py
    DisableForwarding yes
    AllowTcpForwarding no
    AllowStreamLocalForwarding no
    AllowAgentForwarding no
    X11Forwarding no
    PermitTunnel no
    PermitTTY no
    PermitUserRC no
    MaxSessions 2
'''


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def effective(config, user):
    return subprocess.check_output(['/usr/sbin/sshd', '-T', '-f', str(config), '-C',
                                    f'user={user},host=134.209.149.217,addr=127.0.0.1'], text=True)


def replace(path, data, mode):
    temporary = path.with_name(path.name+'.new-'+uuid.uuid4().hex)
    temporary.write_text(data)
    temporary.chmod(mode)
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-key', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('The server owner must install this policy as root')
    key = args.public_key.read_text().strip()
    if '\n' in key or not re.fullmatch(r'(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp[0-9]+) [A-Za-z0-9+/=]+(?: [^\r\n]*)?', key):
        parser.error('Supply one SSH public key line, without authorized_keys options')
    fingerprint = subprocess.check_output(['/usr/bin/ssh-keygen', '-lf', str(args.public_key)], text=True).strip()
    source = Path(__file__).resolve().parent
    for name in ['krsaangi_release.py', 'ssh_gateway.py']:
        if not (source/name).read_text().startswith('#!/usr/bin/python3 -I\n'):
            raise ValueError('Helpers must use isolated system Python')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    backup = Path('/root/pedestrian-shield-access-backups')/stamp
    backup.mkdir(parents=True, mode=0o700)
    backup.parent.chmod(0o700)
    old_config = SSHD.read_text()
    old_root_policy = effective(SSHD, 'root')
    shutil.copy2(SSHD, backup/'sshd_config')
    for path in [SUDO, COMMAND, LIB/'ssh_gateway.py', KEYS]:
        if path.exists():
            shutil.copy2(path, backup/path.name)
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        run(['/usr/sbin/useradd', '--create-home', '--home-dir', str(HOME), '--shell', '/bin/sh', '--user-group', USER])
        account = pwd.getpwnam(USER)
    if (account.pw_uid < 1000 or account.pw_dir != str(HOME) or account.pw_shell != '/bin/sh'
            or grp.getgrgid(account.pw_gid).gr_name != USER):
        raise ValueError('Existing account does not match the managed demo role')
    groups = [g.gr_name for g in grp.getgrall() if USER in g.gr_mem]
    if groups:
        raise ValueError('The demo account must not belong to supplementary groups: '+','.join(groups))
    run(['/usr/sbin/usermod', '--lock', USER])
    os.chown(HOME, 0, 0)
    HOME.chmod(0o755)
    LIB.mkdir(parents=True, exist_ok=True)
    LIB.chmod(0o755)
    for origin, destination in [(source/'krsaangi_release.py', COMMAND), (source/'ssh_gateway.py', LIB/'ssh_gateway.py')]:
        replace(destination, origin.read_text(), 0o755)
    STATE.mkdir(exist_ok=True)
    STATE.chmod(0o755)
    inbox = STATE/'inbox'
    inbox.mkdir(exist_ok=True)
    os.chown(inbox, account.pw_uid, account.pw_gid)
    inbox.chmod(0o700)
    (STATE/'private').mkdir(exist_ok=True)
    (STATE/'private').chmod(0o700)
    upload_lock = STATE/'upload.lock'
    upload_lock.touch(exist_ok=True)
    os.chown(upload_lock, 0, account.pw_gid)
    upload_lock.chmod(0o660)
    KEYS.parent.mkdir(exist_ok=True)
    KEYS.parent.chmod(0o755)
    with tempfile.TemporaryDirectory(prefix='demo-policy-') as tmp:
        candidate_rule = Path(tmp)/'sudoers'
        candidate_rule.write_text(RULE)
        run(['/usr/sbin/visudo', '-cf', str(candidate_rule)], stdout=subprocess.DEVNULL)
        stripped = re.sub(re.escape(BEGIN)+r'.*?'+re.escape(END)+r'\n?', '', old_config, flags=re.S)
        candidate = Path(tmp)/'sshd_config'
        candidate.write_text(stripped.rstrip()+'\n\n'+BEGIN+'\n'+MATCH+END+'\n')
        run(['/usr/sbin/sshd', '-t', '-f', str(candidate)])
        if effective(candidate, 'root') != old_root_policy:
            raise ValueError('Proposed configuration would change the owner SSH policy')
        role_policy = effective(candidate, USER)
        for expected in ['forcecommand '+str(LIB/'ssh_gateway.py'), 'disableforwarding yes',
                         'passwordauthentication no', 'permittty no', 'permituserrc no',
                         'authorizedkeysfile '+str(KEYS)]:
            if expected not in role_policy.splitlines():
                raise ValueError('Restricted SSH policy did not apply: '+expected)
        replace(SUDO, RULE, 0o440)
        run(['/usr/sbin/visudo', '-c'], stdout=subprocess.DEVNULL)
        replace(SSHD, candidate.read_text(), 0o644)
    try:
        run(['/usr/sbin/sshd', '-t'])
        run(['/usr/bin/systemctl', 'reload', 'ssh.service'])
    except Exception:
        replace(SSHD, old_config, 0o644)
        run(['/usr/sbin/sshd', '-t'])
        run(['/usr/bin/systemctl', 'reload', 'ssh.service'])
        raise
    # Enable this one key only after the effective restrictions have passed.
    replace(KEYS, 'restrict '+key+'\n', 0o644)
    info = {'user': USER, 'protocol': 2, 'public_key_fingerprint': fingerprint,
            'policy_backup': str(backup),
            'helpers_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in [COMMAND, LIB/'ssh_gateway.py']}}
    replace(STATE/'installed.json', json.dumps(info, indent=2), 0o600)
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main()
