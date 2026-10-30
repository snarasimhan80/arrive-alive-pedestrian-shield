# Demo-only deployment access

The `footpath-deployer` account is restricted to this demo. A dedicated SSH
key can be handed to the developer without sharing the server owner's key
or a server administrator password. The key is **not included in this
repository, a source ZIP, or a Docker image**.

## Developer setup

Receive the private deployment key through the owner's private handover.
Save it outside the checkout, for example:

```sh
mkdir -p ~/.ssh
chmod 700 ~/.ssh
chmod 600 ~/.ssh/krsaangi-footpath-deployer
ssh -i ~/.ssh/krsaangi-footpath-deployer -o IdentitiesOnly=yes footpath-deployer@134.209.149.217 status
```

On the first connection, compare the server fingerprint with the one in
the private handover. Do not disable host-key checking. A successful login
prints release/status JSON; it does not open a terminal shell.

From the local checkout and Python venv:

```sh
python scripts/deploy_krsaangi.py status --identity ~/.ssh/krsaangi-footpath-deployer
python scripts/deploy_krsaangi.py deploy --identity ~/.ssh/krsaangi-footpath-deployer --dry-run
python scripts/deploy_krsaangi.py deploy --identity ~/.ssh/krsaangi-footpath-deployer --skip-tests
python scripts/deploy_krsaangi.py logs --identity ~/.ssh/krsaangi-footpath-deployer
python scripts/deploy_krsaangi.py rollback --identity ~/.ssh/krsaangi-footpath-deployer --backup BACKUP_ID --dry-run
```

Use `--skip-tests` only after matching full local clip acceptance passes.
Remove `--dry-run` to perform a checked rollback. The GitHub review/push
workflow and verification steps are in `DEPLOYMENT.md`.

## What the account can do

- Upload one bounded ZIP through the forced gateway.
- Ask the fixed helper to validate and deploy it to
  `/opt/arrive-alive-module3`, retaining the installed Python environment.
- Roll back this demo's code using a validated backup ID.
- Check this demo's release metadata and read its last 200 journal lines.

It cannot open a shell, use SCP/SFTP, forward ports, run arbitrary commands,
run general sudo or Python as root, modify SSH/Nginx/systemd configuration,
install packages, or manage another service. It cannot directly write the
live code tree or the installed privileged helpers. Runtime dependency
changes and access-policy changes remain owner tasks.

Someone who can deploy application code can run that code as the demo's
unprivileged service user and access the demo's own uploaded data. This is
an application-maintainer role. The app retains its systemd restrictions,
including `DynamicUser`, `NoNewPrivileges`, read-only system paths and a
private temporary directory. This role does not grant a general OS login.

## How the boundary works

1. SSH uses `ForceCommand` to run the root-owned gateway, with forwarding,
   PTY and user SSH startup scripts disabled. The account's home and its
   central authorized-key file are root-owned; password login is disabled.
2. The gateway accepts only a fixed command grammar. It never runs a client
   command through a shell and does not accept an executable path.
3. Sudo permits only `/usr/local/sbin/pedestrian-shield-release`. It does
   not permit `sudo python3`, `sh`, `systemctl`, `journalctl` or general
   root commands. The helper uses isolated system Python (`-I`).
4. The helper is installed outside the application tree and is not updated
   by a submitted release. Only the owner installs reviewed policy changes.
5. Uploads are opened without following symlinks, bounded, and copied into
   root-only storage before validation/extraction. Manifest checks, archive
   path checks and syntax checks operate on that same private snapshot.
6. The only writable release destination and service name are fixed in the
   helper. Backup IDs and upload tokens have strict formats. Runtime
   requirements cannot change through this role.
7. Uploads are limited to 256 MiB, three queued files, and expire after one
   hour on a later upload. Release size/file limits, an 8 GiB free-space
   floor and a ten-entry backup limit bound disk use. The owner maintains
   backups; the account has no arbitrary server-file deletion command.

These SSH controls follow the official
[OpenSSH server configuration reference](https://man.openbsd.org/sshd_config#ForceCommand).
The forced command is paired with `DisableForwarding`; forcing a command
alone does not disable forwarding.

## Owner-only installation and key rotation

An administrator reviews and copies `install_demo_access.py`,
`krsaangi_release.py` and `ssh_gateway.py` from the trusted source checkout
to a **root-owned staging directory outside the deployed app**. Run there:

```sh
/usr/bin/python3 -I /root/pedestrian-shield-access-stage/install_demo_access.py \
  --public-key /root/pedestrian-shield-access-stage/developer.pub
```

The installer creates/checks the unprivileged account, installs root-owned
helpers and one narrowly scoped sudo command, checks SSH syntax and the
effective role policy, confirms the owner's effective SSH policy is
unchanged, then reloads SSH and enables the supplied public key. It backs
up policy files under `/root/pedestrian-shield-access-backups/`.
The account belongs only to its own primary group, not `sudo`, `adm`, or
`docker`. Policy metadata and public-key fingerprint are recorded in
`/var/lib/pedestrian-shield-deploy/installed.json`.

Rerun the owner installer with another public key to rotate the credential.
It replaces the authorized role key. Never execute a policy installer from
the live app merely because a collaborator included it in a release;
review it separately first. The private key stays with its intended holder.

## Owner-only revocation

To block new logins without affecting other users:

```sh
truncate -s 0 /etc/ssh/authorized_keys/footpath-deployer
```

To terminate the account's current SSH/gateway sessions too, the owner may
use `pkill -u footpath-deployer`. A privileged release operation already in
progress may finish; inspect this demo's status before further action.
Revoke GitHub collaborator access separately. Do not change the owner's
SSH key or remove this demo's uploaded data to revoke a developer.
