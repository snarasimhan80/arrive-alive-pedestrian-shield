from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
import sys
from download_helpers import download

gemma = "--gemma" in sys.argv
REPO = "mlx-community/gemma-3-12b-it-4bit" if gemma else "dgrauet/ltx-2.3-mlx-q4"
OUT = Path(__file__).resolve().parent / "models" / ("gemma-3-12b-4bit" if gemma else "ltx-2.3-q4")
OUT.mkdir(parents=True, exist_ok=True)
tree = requests.get(f"https://huggingface.co/api/models/{REPO}/tree/main?recursive=true&expand=false", timeout=30).json()
weights = {"transformer-distilled-1.1.safetensors", "connector.safetensors", "vae_encoder.safetensors", "vae_decoder.safetensors", "audio_vae.safetensors", "vocoder.safetensors", "spatial_upscaler_x2_v1_1.safetensors"}
files = [x for x in tree if x.get("type") == "file" and (gemma and not x["path"].startswith(".") or x["path"] in weights or x["path"].endswith(".json") or x["path"] in {"LICENSE", "README.md"})]

def get_file(item):
    name, size = item["path"], item["size"]
    path = OUT / name
    if path.exists() and path.stat().st_size == size:
        print("CACHED", name, flush=True)
        return
    url = f"https://huggingface.co/{REPO}/resolve/main/{name}?download=true"
    if size > 8*1024*1024:
        download(url, path, size, item.get("lfs", {}).get("oid"))
    else:
        response = requests.get(url, timeout=90)
        response.raise_for_status()
        path.write_bytes(response.content)
        print("READY", name, flush=True)

with ThreadPoolExecutor(max_workers=2) as executor:
    list(executor.map(get_file, files))
print("MODEL READY", OUT, flush=True)
