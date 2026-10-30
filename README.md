# Arrive Alive AI — Pedestrian Shield

Module 3 demo: upload a short fixed-camera street video, review possible
footpath obstructions, and see tracked pedestrians stepping into the road
highlighted in red. The simple page calculates a **visual concern score**.
The advanced setup supports the proposal's FR-23/24/25 estimates with
explicit site inputs. Neither score predicts crashes or mortality.

**Live demo:** https://134.209.149.217/footpath-demo/

## Run locally

You need Git, **Python 3.12** and **FFmpeg**. macOS and Linux are supported;
use WSL for the Linux instructions on Windows. No cloud API key, Ollama,
external LLM or video-generation model is needed to run the detector.
The two detector weights and ready-to-upload MP4s are included in the repo.

```sh
git clone https://github.com/snarasimhan80/arrive-alive-pedestrian-shield.git
cd arrive-alive-pedestrian-shield
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

On **macOS**, install PyTorch from PyPI:

```sh
python -m pip install torch==2.14.0 torchvision==0.29.0
```

On **Linux**, install the CPU packages first:

```sh
python -m pip install torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu
```

Then, on either platform:

```sh
python -m pip install -r requirements-hosted.txt
python app.py
```

Open **http://127.0.0.1:8765/**. Choose an example's **Analyze this video**
button, or download its MP4 and upload it yourself. Other camera views need
a one-time footpath and road marking at `/analyze`; arbitrary footpaths are
not automatically identified. Stop the development server with Ctrl+C.

For FFmpeg installation, Docker, settings and troubleshooting, see
[Local development](docs/LOCAL_DEVELOPMENT.md).

## Make a change

1. Create a branch: `git switch -c your-change`.
2. Edit the files described in [Development guide](docs/DEVELOPMENT.md).
3. Run the operations tests and all five clip checks:

   ```sh
   python -m unittest discover -s tests -v
   python .video-tools/validate_clips.py --mode local
   ```

4. Check the page in a browser. Review red tracks, returns and the original
   proposal's ten illustrative rows. Commit and push your branch; open a PR.
5. After review and merge, deploy the clean `main` commit as described below.

The four generated clips demonstrate parked-car, shop-goods, motorcycle and
bicycle obstructions. A separate filmed clear-footpath control should have
zero tracked road exits and zero obstruction flags. Passing these examples
checks the workflow; it does not establish accuracy on actual CCTV footage.

## Deploy to Krsaangi

An administrator must grant you your **own SSH access** to the server and
permission to run deployment commands with `sudo -n`. A GitHub invitation
alone does not grant server access. No SSH private key or server password is
stored here. Do not share the owner's key.

From a reviewed, pushed and clean `main` checkout, with the venv active:

```sh
git switch main
git pull --ff-only
python scripts/deploy_krsaangi.py deploy --host YOUR_SSH_USER@134.209.149.217 --dry-run
python scripts/deploy_krsaangi.py deploy --host YOUR_SSH_USER@134.209.149.217
```

The helper checks the pushed Git commit, reruns clip acceptance, packages
source and models, checks the uploaded archive, backs up the app, retains
its installed Python environment, restarts **only** the demo service, and
restores the previous app if startup health fails. Uploads live outside the
code directory and remain in place. Allow a brief interruption when the
service restarts; wait for active analyses to finish first.

```sh
curl --fail https://134.209.149.217/footpath-demo/health
python .video-tools/validate_clips.py --mode public
python scripts/deploy_krsaangi.py status --host YOUR_SSH_USER@134.209.149.217
```

**[Full deployment, rollback and dependency maintenance guide](docs/DEPLOYMENT.md)**
includes the exact paths, service configuration, access prerequisites,
post-deploy checks and recovery commands. Deployment is manual; pushing to
GitHub does not automatically modify the server.

## Handover contents

| Path | Purpose |
|---|---|
| `app.py` | Flask routes, upload limits, jobs and results |
| `quick_screen.py`, `pedestrian_tracks.py` | Simple-page score and path-to-road tracking |
| `analyzer.py`, `obstructions.py` | Segmentation and shop-goods detection |
| `scene_signals.py`, `site_table.py` | Advanced site estimates and ranking |
| `templates/`, `static/` | UI, proposal and original illustrative table |
| `examples/` | MP4s, camera polygons, provenance and historical checks |
| `.video-tools/` | Optional asset-generation and clip-acceptance scripts |
| `scripts/`, `deploy/`, `tests/` | Packaging, deployment and recovery checks |

The deployed `/source.zip` includes the source and a `RELEASE.json` identifying
the deployed Git commit. See [SOURCE_README.md](SOURCE_README.md) for formulas
and model limitations, and [Handover checklist](docs/HANDOVER.md) for access.

## License and media

AGPL-3.0; retain [LICENSE](LICENSE) and the updated public source download.
The Ultralytics detectors are included under the existing AGPL distribution.
An Enterprise model license has not been purchased or verified.
Generated footage is explicitly labelled. Its provenance, regeneration
prompts and separate LTX license are in
[examples/generated-scenarios/GENERATION.md](examples/generated-scenarios/GENERATION.md).
The optional generator weights are not needed to run the demo and are not
included. Filmed controls retain their source credits in
`examples/real-scenarios/manifest.json`.
