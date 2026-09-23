"""App real (FastAPI + cliente Ollama real contra el mock) con un TTS sintético (tono de 0,4 s)."""
import math, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "api"))
from app.config import Settings
from app.main import create_app
from app.tts.common import pcm_to_wav

class ToneTTS:
    name = "tono"
    def __init__(self, personas): self.profiles = {c: {"voice": "x"} for c in personas}
    def prefetch(self): pass
    def status(self): return {"engine": "tono", "ready": True}
    def voices_info(self): return {}
    def synth(self, cid, text):
        sr = 22050; f = 180 + 40 * (hash(cid) % 5)
        pcm = b"".join(struct.pack("<h", int(9000 * math.sin(2 * math.pi * f * i / sr) * (0.5 + 0.5 * math.sin(i / 900)))) for i in range(int(sr * 0.6)))
        return pcm_to_wav(pcm, sr)

def make():
    st = Settings({"CONFIG_DIR": str(ROOT / "config"), "WEB_DIR": str(ROOT / "web"), "OLLAMA_URL": "http://127.0.0.1:11555", "PULL_ON_START": "0"})
    from app.config import Store
    return create_app(st, tts=ToneTTS(Store(st.config_dir).personas), start_background=False)
