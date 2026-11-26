"""
Embedding service for the scheme library (runs on the lab box, CPU only, never touches the GPU).

POST /embed   {"texts": ["..", ".."]}  ->  {"model": "...", "dim": 1024, "vectors": [[..], ..]}
GET  /health  ->  {"ok": true, "model": "...", "dim": 1024}
GET  /stats   ->  GPU memory, system RAM and per-model-service RAM on this box (read-only, for the status panel)

Model: BAAI/bge-m3 (MIT), dense vectors, L2-normalised so cosine distance is a dot product.
Start under a RAM and CPU cap (see docs), for example:
  systemd-run --user --unit=embed-service -p MemoryMax=6G -p CPUQuota=200% \
    -E CUDA_VISIBLE_DEVICES= /home/apps/miniconda3/envs/langchain/bin/python embed_service.py
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["CUDA_VISIBLE_DEVICES"] = ""          # CPU only: the GPU belongs to the Qwen boss
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from sentence_transformers import SentenceTransformer  # noqa: E402

MODEL_DIR = os.environ.get("EMBED_MODEL_DIR", "/home/admin/models/bge-m3")
PORT = int(os.environ.get("EMBED_PORT", "8095"))
MAX_BATCH, MAX_CHARS = 64, 2000

model = SentenceTransformer(MODEL_DIR, device="cpu")
model.max_seq_length = 512
DIM = model.get_sentence_embedding_dimension()
lock = threading.Lock()


UNITS = ("qwen-boss", "gemma-worker", "gemma-math", "embed-service")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=4).stdout
    except Exception:
        return ""


def lab_stats() -> dict:
    """Live lab-box resource use for the app's status panel: GPU memory, system RAM, and RAM per model service."""
    gpus = []
    for line in _run(["nvidia-smi", "--query-gpu=index,name,memory.used,memory.total", "--format=csv,noheader,nounits"]).splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) == 4 and p[2].isdigit():
            gpus.append({"index": int(p[0]), "name": p[1], "used_mib": int(p[2]), "total_mib": int(p[3])})
    mem = {}
    for line in open("/proc/meminfo"):
        k, _, v = line.partition(":")
        if k in ("MemTotal", "MemAvailable"):
            mem[k] = int(v.split()[0]) // 1024
    units = {}
    for u in UNITS:
        out = _run(["systemctl", "--user", "show", f"{u}.service", "-p", "MemoryCurrent", "-p", "MemoryMax"])
        kv = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        cur, cap = kv.get("MemoryCurrent", ""), kv.get("MemoryMax", "")
        units[u] = {"ram_mib": int(cur) // (1024 * 1024) if cur.isdigit() else None,
                    "ram_cap_mib": int(cap) // (1024 * 1024) if cap.isdigit() else None}
    return {"gpus": gpus, "ram_total_mib": mem.get("MemTotal"), "ram_available_mib": mem.get("MemAvailable"), "units": units}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"ok": True, "model": MODEL_DIR, "dim": DIM})
        elif self.path == "/stats":
            self._send(200, lab_stats())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/embed":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            texts = json.loads(self.rfile.read(n) or b"{}").get("texts")
            if not isinstance(texts, list) or not texts or len(texts) > MAX_BATCH:
                return self._send(400, {"error": f"texts must be a list of 1..{MAX_BATCH} strings"})
            texts = [str(t)[:MAX_CHARS] for t in texts]
            with lock:
                vecs = model.encode(texts, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
            self._send(200, {"model": MODEL_DIR, "dim": DIM, "vectors": [v.tolist() for v in vecs]})
        except Exception as e:                     # never take the service down on one bad request
            self._send(500, {"error": str(e)[:200]})

    def log_message(self, *a) -> None:
        pass


if __name__ == "__main__":
    print(f"embed service on :{PORT}, dim {DIM}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
