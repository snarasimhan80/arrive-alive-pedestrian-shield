"""Resume large public model downloads with bounded parallel byte ranges."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import json
import os
import threading
import time
import requests


def download(url, path, size, sha256=None, chunk_size=8*1024*1024, workers=8):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size == size:
        print("CACHED", path.name, flush=True)
        return
    part = path.with_suffix(path.suffix + ".part")
    ledger = path.with_suffix(path.suffix + ".ranges.json")
    if ledger.exists():
        state = json.loads(ledger.read_text())
    else:
        state = {"prefix": part.stat().st_size if part.exists() else 0, "done": []}
    prefix = state["prefix"]
    done = set(state["done"])
    probe = requests.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=30)
    probe.raise_for_status()
    direct_url = probe.url
    probe.close()
    fd = os.open(part, os.O_RDWR | os.O_CREAT, 0o644)
    os.ftruncate(fd, size)
    lock = threading.Lock()
    ranges = [(i, start, min(size-1, start+chunk_size-1))
              for i, start in enumerate(range(prefix, size, chunk_size)) if i not in done]
    total = len(ranges) + len(done)

    def one(item):
        index, start, end = item
        for attempt in range(4):
            try:
                response = requests.get(direct_url, headers={"Range": f"bytes={start}-{end}"}, timeout=(20, 90))
                response.raise_for_status()
                if response.status_code != 206 or len(response.content) != end-start+1:
                    raise RuntimeError(f"Bad range response {response.status_code}: {path.name}")
                os.pwrite(fd, response.content, start)
                with lock:
                    done.add(index)
                    ledger.write_text(json.dumps({"prefix": prefix, "done": sorted(done)}))
                    if len(done) % 32 == 0 or len(done) == total:
                        print("PROGRESS", path.name, len(done), "/", total, flush=True)
                return
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(attempt + 1)

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(one, ranges))
    finally:
        os.close(fd)
    if sha256:
        digest = hashlib.sha256()
        with part.open("rb") as handle:
            for chunk in iter(lambda: handle.read(16*1024*1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != sha256:
            raise RuntimeError(f"SHA256 mismatch: {path.name}")
    part.replace(path)
    ledger.unlink(missing_ok=True)
    print("READY", path.name, round(size/1e9, 2), "GB", flush=True)
