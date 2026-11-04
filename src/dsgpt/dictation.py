"""Bounded local streaming speech recognition. Audio and drafts never touch disk."""

import base64
import binascii
import json
import threading
import time
from uuid import uuid4

from fastapi import HTTPException


class Dictation:
    def __init__(self, directory, factory=None):
        self.directory = directory / "voice" / "model"
        self.factory = factory
        self.model = None
        self.sessions = {}
        self.lock = threading.RLock()

    def status(self):
        return {
            "ready": self.factory is not None or (self.directory / "am/final.mdl").is_file(),
            "language": "en-US",
            "audio_saved": False,
            "processing": "local_pc",
        }

    def start(self, owner):
        with self.lock:
            self._expire()
            for identifier in list(self.sessions):
                if self.sessions[identifier]["owner"] == owner:
                    del self.sessions[identifier]
            if len(self.sessions) >= 4:
                raise HTTPException(429, "Other dictation sessions are active")
            if self.factory:
                recognizer = self.factory()
            else:
                if not self.status()["ready"]:
                    raise HTTPException(
                        503,
                        "Voice files are still being prepared on your PC. Setup installs them "
                        "automatically.",
                    )
                from vosk import KaldiRecognizer, Model, SetLogLevel

                SetLogLevel(-1)
                if self.model is None:
                    self.model = Model(str(self.directory))
                recognizer = KaldiRecognizer(self.model, 16000)
            identifier = str(uuid4())
            self.sessions[identifier] = {
                "owner": owner,
                "recognizer": recognizer,
                "time": time.monotonic(),
                "bytes": 0,
                "seq": 0,
                "text": "",
                "last": None,
            }
            return {"id": identifier, "sample_rate": 16000, "max_seconds": 600}

    def _expire(self):
        now = time.monotonic()
        for key in list(self.sessions):
            if now - self.sessions[key]["time"] > 30:
                del self.sessions[key]

    def chunk(self, owner, identifier, seq, audio, final=False):
        with self.lock:
            self._expire()
            session = self.sessions.get(identifier)
            if not session or session["owner"] != owner:
                raise HTTPException(404, "Dictation session expired. Tap the microphone again.")
            try:
                pcm = base64.b64decode(audio, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise HTTPException(422, "Invalid audio") from exc
            if len(pcm) > 32000 or len(pcm) % 2:
                raise HTTPException(422, "Use at most one second of 16 kHz mono PCM")
            if seq != session["seq"]:
                raise HTTPException(409, "Dictation audio arrived out of order; restart recording")
            session["seq"] += 1
            session["time"] = time.monotonic()
            session["bytes"] += len(pcm)
            if session["bytes"] > 32000 * 600:
                del self.sessions[identifier]
                raise HTTPException(
                    413, "Ten-minute dictation limit reached. Start another recording."
                )
            recognizer = session["recognizer"]
            if pcm and recognizer.AcceptWaveform(pcm):
                segment = json.loads(recognizer.Result()).get("text", "")
                session["text"] = (session["text"] + " " + segment).strip()
            if final:
                partial = json.loads(recognizer.FinalResult()).get("text", "")
                del self.sessions[identifier]
            else:
                partial = json.loads(recognizer.PartialResult()).get("partial", "")
            return {"text": (session["text"] + " " + partial).strip(), "final": final}

    def cancel(self, owner, identifier):
        with self.lock:
            session = self.sessions.get(identifier)
            if session and session["owner"] == owner:
                del self.sessions[identifier]
        return {"stopped": True}
