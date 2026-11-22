"""
Local speech-to-text service for SaralcreditAI (free, no key, no cloud).

Engine: faster-whisper (MIT) on CTranslate2 (MIT) with OpenAI Whisper weights (MIT).
Runs on the laptop CPU from a separate virtual environment so nothing is installed into the main Python.
Everything it writes (model files, temp audio) stays under D:\\param shavak\\project KS.

    D:\\param shavak\\project KS\\.venv-stt\\Scripts\\python.exe munimai\\stt\\stt_service.py

POST /transcribe?lang=en   body = 16-bit PCM WAV bytes (the gateway converts other formats first)  ->  {"text": "...", "seconds": 1.2, "model": "small.en"}
GET  /health                                                                 ->  {"ok": true, "model": "small.en"}

Listens on 127.0.0.1 only. English by default; other languages need a multilingual model (set STT_MODEL=small).
"""
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(os.environ.get("STT_ROOT", r"D:\param shavak\project KS"))
(ROOT / "tmp").mkdir(parents=True, exist_ok=True)
(ROOT / "models" / "whisper").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf"))
os.environ.setdefault("TEMP", str(ROOT / "tmp"))
os.environ.setdefault("TMP", str(ROOT / "tmp"))
tempfile.tempdir = str(ROOT / "tmp")

from faster_whisper import WhisperModel  # noqa: E402

MODEL_NAME = os.environ.get("STT_MODEL", "small.en")
PORT = int(os.environ.get("STT_PORT", "8094"))
THREADS = int(os.environ.get("STT_THREADS", "6"))
MAX_BYTES = 25 * 1024 * 1024

_model = None
_lock = threading.Lock()


def model() -> WhisperModel:
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8", cpu_threads=THREADS,
                                      download_root=str(ROOT / "models" / "whisper"))
    return _model


def wav_to_array(data: bytes):
    """16-bit PCM WAV bytes -> mono float32 at 16 kHz. We read the WAV ourselves so no audio-decoding library is needed."""
    import io
    import wave

    import numpy as np
    with wave.open(io.BytesIO(data)) as w:
        ch, rate, width, n = w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()
        if width != 2:
            raise ValueError("send 16-bit PCM WAV")
        pcm = np.frombuffer(w.readframes(n), dtype="<i2").astype("float32") / 32768.0
    if ch > 1:
        pcm = pcm.reshape(-1, ch).mean(axis=1)
    if rate != 16000 and len(pcm):
        pcm = np.interp(np.linspace(0, len(pcm) - 1, int(len(pcm) * 16000 / rate)), np.arange(len(pcm)), pcm).astype("float32")
    return pcm


def transcribe(data: bytes, lang: str) -> dict:
    t0 = time.time()
    audio = wav_to_array(data)
    language = "en" if MODEL_NAME.endswith(".en") else (lang or None)
    segs, info = model().transcribe(audio, language=language, beam_size=1, vad_filter=True,
                                    vad_parameters={"min_silence_duration_ms": 400}, condition_on_previous_text=False)
    text = " ".join(s.text.strip() for s in segs).strip()
    return {"text": text, "seconds": round(time.time() - t0, 2), "audio_seconds": round(len(audio) / 16000, 2), "model": MODEL_NAME}


class H(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            return self._json(200, {"ok": True, "model": MODEL_NAME, "loaded": _model is not None})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/transcribe":
            return self._json(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BYTES:
            return self._json(413, {"error": "audio must be between 1 byte and 25 MB"})
        data = self.rfile.read(n)
        try:
            self._json(200, transcribe(data, parse_qs(u.query).get("lang", ["en"])[0]))
        except Exception as e:  # never crash the service on one bad clip
            self._json(500, {"error": str(e)[:300]})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Loading {MODEL_NAME} (first run downloads it into {ROOT / 'models' / 'whisper'}) ...", flush=True)
    model()
    print(f"Ready on http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
