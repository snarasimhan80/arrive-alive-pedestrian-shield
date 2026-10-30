# Local development

## Prerequisites

- Python 3.12, Git and FFmpeg on PATH.
- At least 4 GB available memory for the web demo and local checks; CPU
  inference is sufficient. The public service has a 1 GB memory limit and
  runs one analysis job at a time.
- The model and sample files from an ordinary `git clone`. Git LFS is not
  required. No inference API key is needed.

macOS with Homebrew:

```sh
brew install python@3.12 ffmpeg
```

Ubuntu 24.04:

```sh
sudo apt-get update
sudo apt-get install python3.12 python3.12-venv ffmpeg libgl1 libglib2.0-0
```

Follow the native environment and PyTorch install commands in the root README.
Then use `python app.py`; it binds only `127.0.0.1:8765`.
Use a separate shell with the same venv active for the clip checks.

## Docker alternative

With a running Docker engine:

```sh
docker build -t pedestrian-shield .
docker run --rm -p 127.0.0.1:7860:7860 pedestrian-shield
```

Open http://127.0.0.1:7860/ . The image uses public-demo limits, a CPU detector,
one Gunicorn worker and queued analysis. Uploaded files inside a disposable
container disappear when it is removed. To retain them locally:

```sh
docker volume create pedestrian-shield-jobs
docker run --rm -p 127.0.0.1:7860:7860 \
  -e DEMO_JOBS_DIR=/home/user/jobs \
  -v pedestrian-shield-jobs:/home/user/jobs pedestrian-shield
```

The Dockerfile generates a source download inside the image. A build from
a source snapshot is labelled unvalidated and cannot be sent through the
Krsaangi deployment helper. Production releases require a clean Git commit
and matching clip acceptance. The Krsaangi server currently runs native
Python/systemd, not Docker; use the deployment helper for that server.

## Settings

| Variable | Local default | Public server |
|---|---|---|
| `HOSTED_DEMO` | `0`: 250 MB, 120 seconds | `1`: 25 MB, 30 seconds |
| `DEMO_JOBS_DIR` | `jobs/` in the checkout | `/var/lib/arrive-alive-module3/jobs` |
| `YOLO_CONFIG_DIR` | Ultralytics default | configured in systemd |
| `MPLCONFIGDIR` | Matplotlib default | configured in systemd |

The public service expires uploads older than 24 hours on a later request.
Result URLs grant access to the corresponding outputs. Local jobs are
ignored by Git and never enter a source release.

To exercise the public limits without changing the deployed server:

```sh
HOSTED_DEMO=1 python app.py
```

## Troubleshooting

- **Port occupied:** stop the older development process, or use
  `python -m flask --app app run --host 127.0.0.1 --port 8766`.
- **Missing FFmpeg:** `ffmpeg -version` must work in the same shell.
- **Missing weights:** restore `yolov8n-seg.pt` and `obstruction-world.pt`
  from Git. Do not replace them with unrelated model versions.
- **No displacement measured for a new camera:** the four saved examples
  have reviewed polygon presets. Mark another camera at `/analyze`.
- **Slow or memory-heavy inference:** keep one analysis worker. Do not add
  Gunicorn processes on the small Krsaangi host; each loads its own models.
- **A clip check fails:** inspect `artifacts/videos/` and its `report.json`.
  Review the actual movement before changing expected counts. Small
  numerical differences between CPU builds can affect detections; exact
  scores are observations, not hard-coded acceptance targets.
- **TLS errors on public tests:** fix the certificate or local CA store.
  The test runner verifies HTTPS and does not disable certificate checks.

Run artifacts are written to ignored `artifacts/`; historical evidence in
`examples/generated-scenarios/VALIDATION.json` stays unchanged.

## Hosting on another server

The code and included models are self-contained. You do not need a Krsaangi
login to host your own copy. On a Linux server you control, clone this repo,
install Docker, then build and start the container:

```sh
docker build -t pedestrian-shield .
docker volume create pedestrian-shield-jobs
docker run -d --restart unless-stopped --name pedestrian-shield \
  -p 127.0.0.1:7860:7860 \
  -e DEMO_JOBS_DIR=/home/user/jobs \
  -v pedestrian-shield-jobs:/home/user/jobs pedestrian-shield
```

Point your own HTTPS reverse proxy/domain at `127.0.0.1:7860`. The app serves
at `/`; if mounting under a prefix, strip it in the reverse proxy as shown
in the example under `deploy/`. Use your own certificates and server login.
Keep the AGPL source download available and the generated footage labelled.
The Krsaangi deployment helper is specific to the existing Krsaangi service
and is not needed for your own Docker instance.
