"""Package source, models, examples and handover docs; never package uploads."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
import datetime
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ['quick_screen.py', 'analyzer.py', 'obstructions.py', 'pedestrian_tracks.py']
EXPECTED = {'01-parked-car': 2, '02-shop-goods': 1, '03-motorbike': 1,
            '04-bicycles': 1, 'clear-control': 0}
EXCLUDED = {'.git', '.venv', 'venv', '__pycache__', 'jobs', 'artifacts', 'dist',
            '.pytest_cache', 'models', 'ltx-2-mlx', 'clip', 'validation', 'real-candidates'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validation_file():
    candidate = ROOT/'artifacts/VALIDATION.json'
    return candidate if candidate.exists() else ROOT/'examples/generated-scenarios/VALIDATION.json'


def check_validation():
    data = json.loads(validation_file().read_text())
    sha = hashlib.sha256()
    for name in ANALYSIS:
        sha.update((ROOT/name).read_bytes())
    local = data.get('local', {})
    if local.get('analysis_code_sha256') != sha.hexdigest():
        raise RuntimeError('Analysis changed: run .video-tools/validate_clips.py --mode local first')
    runs = {item['slug']: item for item in local.get('runs', [])}
    for slug, expected in EXPECTED.items():
        item = runs.get(slug, {})
        source = (ROOT/'examples/real-scenarios/02-real-clear-path.mp4' if slug == 'clear-control'
                  else ROOT/'examples/generated-scenarios'/(slug+'.mp4'))
        if item.get('source_sha256') != digest(source):
            raise RuntimeError('Sample changed since validation: '+slug)
        if any(item.get(key) != expected for key in ['exits', 'returns', 'near_obstruction']):
            raise RuntimeError('Movement acceptance failed: '+slug)
        if item['source_video'] != item['marked_video']:
            raise RuntimeError('Source frame preservation failed: '+slug)
        if expected and not item['obstruction_frames']:
            raise RuntimeError('Missing obstruction: '+slug)
        if not expected and (item['obstruction_frames'] or item['road_person_seconds']):
            raise RuntimeError('False alarm on clear control')


def include(path):
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED for part in relative.parts):
        return False
    name = path.name
    if name.startswith(('.env', 'id_rsa', 'id_ed25519', 'krsaangi-footpath-deployer')) or name == 'Pedestrian-Shield-Deployment-Access.zip':
        return False
    return not ((name.startswith('source') and name.endswith('.zip'))
                or name in {'.DS_Store', 'BUILD_MANIFEST.json', 'RELEASE.json', 'generation.log', 'render-command.json', 'generated.mp4'}
                or name.endswith(('.pem', '.key', '.pyc', '-raw.mp4')))


def build(allow_unvalidated=False):
    if (ROOT/'.git').exists() and not allow_unvalidated:
        dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
        if dirty:
            raise RuntimeError('Commit source changes before building a validated Git release')
    if not allow_unvalidated:
        check_validation()
    files = {}
    # Git provides the publication boundary. The fallback is for downloaded
    # source snapshots and Docker, where .git is intentionally absent.
    if (ROOT/'.git').exists():
        output = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT)
        paths = [ROOT/name.decode() for name in output.split(b'\0') if name]
        if not paths:
            raise RuntimeError('Stage the source files with git add before packaging')
    else:
        paths = [p for p in ROOT.rglob('*') if p.is_file()]
    for path in paths:
        if not include(path):
            continue
        if path.is_symlink():
            raise RuntimeError('Symlinks are not supported in source packages: '+str(path))
        files[path.relative_to(ROOT).as_posix()] = path
    required = ['app.py', 'LICENSE', 'README.md', 'Dockerfile', 'requirements-hosted.txt',
                'yolov8n-seg.pt', 'obstruction-world.pt', 'deploy/krsaangi_release.py']
    if any(name not in files for name in required):
        raise RuntimeError('Source package is incomplete')
    files['examples/generated-scenarios/VALIDATION.json'] = validation_file()
    commit = (subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
              if (ROOT/'.git').exists() else 'source-snapshot')
    release = {'commit': commit, 'repository': 'https://github.com/snarasimhan80/arrive-alive-pedestrian-shield',
               'built_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
               'clip_acceptance_checked': not allow_unvalidated}
    manifest = {name: {'sha256': digest(path), 'bytes': path.stat().st_size} for name, path in sorted(files.items())}
    destination = ROOT/'dist/source.zip'
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination.with_suffix('.new.zip'), 'w', ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr('BUILD_MANIFEST.json', json.dumps(manifest, indent=2))
        archive.writestr('RELEASE.json', json.dumps(release, indent=2))
    destination.with_suffix('.new.zip').replace(destination)
    print(f'Built {destination}: {len(files)} files; commit {commit}', flush=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-unvalidated', action='store_true', help='Development/Docker snapshot only; deployment rejects it')
    build(parser.parse_args().allow_unvalidated)
