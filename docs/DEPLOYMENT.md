# Krsaangi deployment and recovery

This guide updates the **existing** Pedestrian Shield app. It does not
replace the server's Nginx configuration or deploy other Krsaangi apps.
There is no automatic deployment on GitHub push.

## Current server layout

Verified 2026-10-30:

| Item | Value |
|---|---|
| Server | `134.209.149.217` |
| Public URL | `https://134.209.149.217/footpath-demo/` |
| App directory | `/opt/arrive-alive-module3` |
| Python environment | `/opt/arrive-alive-module3/.venv` |
| systemd service | `arrive-alive-module3.service` |
| Local bind | `127.0.0.1:8765` |
| Uploads/results | `/var/lib/arrive-alive-module3/jobs` |
| Helper's code backups | `/opt/arrive-alive-module3-backups/<backup-id>/app` |
| Service definition | `/etc/systemd/system/arrive-alive-module3.service` |
| Existing Nginx site | `/etc/nginx/sites-available/krsaangi` |

The service uses one Gunicorn worker, four HTTP threads and one queued
analysis job. It has `MemoryMax=1G`, `CPUQuota=75%`, `HOSTED_DEMO=1` and
`DynamicUser=yes`. Runtime uploads are outside the code tree. The service
and Nginx reference examples under `deploy/` omit certificates and secrets;
do not overwrite a shared Nginx site with a snippet.

## Restricted deployment access

Use the dedicated `footpath-deployer` account and the private key supplied
by the owner. General administrator access is **not** required for ordinary
code updates. This account has a forced SSH gateway and can only upload a
release, deploy it, roll back, check status or read this demo's recent logs.
It cannot start a shell, run arbitrary sudo/Python commands, use SFTP/SCP,
forward ports, change Nginx, install packages or manage other services.

Put the key at `~/.ssh/krsaangi-footpath-deployer` with mode 600. On the first
connection, confirm the host fingerprint supplied by the owner:

```sh
ssh -i ~/.ssh/krsaangi-footpath-deployer -o IdentitiesOnly=yes footpath-deployer@134.209.149.217 status
python scripts/deploy_krsaangi.py status --identity ~/.ssh/krsaangi-footpath-deployer
```

This command returns JSON instead of a shell; that is intentional. The
client can also use `--host YOUR_SSH_ALIAS` with `IdentityFile` in your SSH
config. See [Restricted access](RESTRICTED_ACCESS.md) for owner installation,
rotation, revocation and the permission boundary.

## Normal update

Activate the local Python environment first. Start from reviewed, pushed
`main`; generated run files belong in ignored `artifacts/`.

```sh
git switch main
git pull --ff-only
git status --short
python -m unittest discover -s tests -v
python scripts/deploy_krsaangi.py deploy --identity ~/.ssh/krsaangi-footpath-deployer --dry-run
```

Dry-run uploads and checks a release but does **not** restart or change the
service. It verifies archive hashes, Python syntax, dependency-file equality
and release metadata. It does not run candidate code on the server.
The helper also reruns all five clips locally and checks `origin/main`.

Wait for active public analyses to finish, then deploy:

```sh
python scripts/deploy_krsaangi.py deploy --identity ~/.ssh/krsaangi-footpath-deployer
```

`--skip-tests` may be added when the matching full local acceptance has
already passed; packaging still rejects stale code/sample hashes. Use it
after a successful dry-run with no source changes to avoid the same local
video run twice. The deployment helper:

1. Requires a clean checkout at the exact commit pushed to `origin/main`.
2. Builds `dist/source.zip` with models, clips, docs, `RELEASE.json` and a
   complete SHA-256 file inventory.
3. Streams the archive to the restricted inbox, snapshots it into root-only
   storage, and checks that immutable copy before stopping
   the service. It rejects unsafe paths, symlinks, missing files, syntax
   errors, checksum mismatches and changed runtime requirement files.
4. Refuses currently visible queued/running analyses, then stops only
   `arrive-alive-module3.service`, renames the old code tree to
   a new backup, moves its existing `.venv` into the new code tree, and
   starts the service. The absolute venv path remains the same.
5. Checks the local `/health`. If startup or health fails, restores the old
   code and the retained venv, then starts it again.
6. Prints the deployed commit and the backup ID. It preserves the upload
   directory, Nginx, systemd configuration and other hosted applications.

Jobs are queued in memory. A restart can interrupt a queued/running job;
its uploaded file remains, but analysis may need to be submitted again.
Startup health verifies that the app starts; the checks below verify actual
public analysis. A semantically bad but healthy release needs manual rollback.

## Verify the deployed update

```sh
curl --fail https://134.209.149.217/footpath-demo/health
python scripts/deploy_krsaangi.py status --identity ~/.ssh/krsaangi-footpath-deployer
python .video-tools/validate_clips.py --mode public
```

Compare the status commit to `git rev-parse HEAD`. In a browser, test an
upload, the red marked video and detailed evidence. Check that all four
examples load and the original ten proposal rows remain. The public runner
uploads renamed videos, checks actual event/return counts, downloads the
marked videos and verifies frame preservation. It creates five short-lived
test jobs; run it during a quiet period on this small server.

The public source ZIP now contains that release's `RELEASE.json`. To check:

```sh
curl --fail -o /tmp/pedestrian-shield-source.zip https://134.209.149.217/footpath-demo/source.zip
unzip -p /tmp/pedestrian-shield-source.zip RELEASE.json
```

## Roll back code

List existing backups, select the exact ID, then restore it:

```sh
python scripts/deploy_krsaangi.py status --identity ~/.ssh/krsaangi-footpath-deployer
python scripts/deploy_krsaangi.py rollback --identity ~/.ssh/krsaangi-footpath-deployer --backup BACKUP_ID --dry-run
python scripts/deploy_krsaangi.py rollback --identity ~/.ssh/krsaangi-footpath-deployer --backup BACKUP_ID
```

Rollback first backs up the current code too. It retains the same installed
venv and uploaded results. Backups made by this helper contain code/source
archives, not a separate venv. Rollback rejects differing requirement files;
use the full-environment recovery below for a dependency migration.
Backups are retained until an administrator deliberately removes them.

## Logs and recovery

```sh
python scripts/deploy_krsaangi.py logs --identity ~/.ssh/krsaangi-footpath-deployer
python scripts/deploy_krsaangi.py status --identity ~/.ssh/krsaangi-footpath-deployer
```

The installed root helper is separate from the deployed app. Updating files
under `deploy/` in a release does not replace that installed helper or the
SSH/sudo policy. Only the server owner can review and install policy changes.
The role refuses new releases below 8 GiB free space or after ten backup
entries; ask the owner to maintain storage if either limit is reached.

Failed new code is kept under `failed-<backup-id>` for diagnosis. If both
deployment and automatic recovery fail, stop and inspect the printed backup
path before moving anything. Do not delete `/var/lib/arrive-alive-module3`.

## Dependency maintenance (administrator, scheduled interruption)

Normal updates deliberately reuse the known installed packages. If changing
`requirements.txt` or `requirements-hosted.txt`, first build/test the new
environment locally and run all clip checks. Native Linux CPU versions
observed on the server are recorded in `DEPLOYED_PACKAGES.txt`; it is a
reference, not a cross-platform lock file. Keep Docker's CPU PyTorch versions
and local setup instructions in sync when changing them.

For a dependency migration, an administrator uses a **full backup including
the old venv**, then builds a new venv at its final absolute path. Python
venv scripts contain that path, so do not build one elsewhere and move it.
Example for an already tested archive uploaded as `/tmp/reviewed-source.zip`:

```sh
# These are commands on the server in an approved root shell.
stamp=$(date -u +%Y%m%dT%H%M%SZ)
previous=/opt/arrive-alive-before-dependencies-$stamp
systemctl stop arrive-alive-module3.service
mv /opt/arrive-alive-module3 "$previous"
mkdir /opt/arrive-alive-module3
unzip /tmp/reviewed-source.zip -d /opt/arrive-alive-module3
cp /tmp/reviewed-source.zip /opt/arrive-alive-module3/source.zip
python3.12 -m venv /opt/arrive-alive-module3/.venv
/opt/arrive-alive-module3/.venv/bin/python -m pip install torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu
/opt/arrive-alive-module3/.venv/bin/python -m pip install -r /opt/arrive-alive-module3/requirements-hosted.txt
systemctl start arrive-alive-module3.service
curl --fail http://127.0.0.1:8765/health
```

Use the reviewed PyTorch versions if intentionally changing them. If install,
startup or analysis fails, restore the complete previous tree and venv:

```sh
systemctl stop arrive-alive-module3.service
mv /opt/arrive-alive-module3 /opt/arrive-alive-failed-dependencies-$stamp
mv "$previous" /opt/arrive-alive-module3
systemctl start arrive-alive-module3.service
curl --fail http://127.0.0.1:8765/health
```

Keep the full previous tree until public clip checks pass. This manual
dependency path is separate from ordinary code deployments; it does not
alter the Nginx site or uploaded footage.
