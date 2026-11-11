"""Small, local-only adapter for the official whisper.cpp HTTP server.

Audio is accepted as WAV bytes and sent to a loopback server in memory. This
module never writes audio or transcription text to disk or diagnostics.
"""

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4


SERVER_RELATIVE = Path(".audio-packages") / "whisper.cpp" / "Release" / "whisper-server.exe"
MODEL_RELATIVE = Path(".audio-packages") / "whisper.cpp" / "Release" / "ggml-small.bin"
INFERENCE_PATH = "/inference"
LANGUAGE = "it"
MAX_WAV_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class WhisperError(RuntimeError):
    """A fixed, non-sensitive adapter failure code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class WhisperBusyError(WhisperError):
    """An inference is already running; callers should skip this audio window."""


def _project_root(root=None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _available_paths(root=None) -> tuple[Path, Path]:
    project = _project_root(root)
    return (project / SERVER_RELATIVE).resolve(), (project / MODEL_RELATIVE).resolve()


class WhisperServer:
    """Own one loopback whisper-server process and serialize inference calls."""

    def __init__(self, root=None, *, readiness_timeout=90.0, request_timeout=60.0):
        if not isinstance(readiness_timeout, (int, float)) or not 1 <= readiness_timeout <= 300:
            raise ValueError("whisper_timeout_non_valido")
        if not isinstance(request_timeout, (int, float)) or not 1 <= request_timeout <= 300:
            raise ValueError("whisper_timeout_non_valido")
        self.root = _project_root(root)
        self.server_path, self.model_path = _available_paths(self.root)
        self.readiness_timeout = float(readiness_timeout)
        self.request_timeout = float(request_timeout)
        self._state_lock = threading.RLock()
        self._inference_lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._port: int | None = None
        self._ready = False

    @classmethod
    def available(cls, root=None) -> bool:
        server, model = _available_paths(root)
        try:
            return server.is_file() and model.is_file() and model.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def _free_loopback_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    @staticmethod
    def _terminate(process: subprocess.Popen | None) -> None:
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        except (OSError, subprocess.SubprocessError):
            try:
                process.kill()
            except (OSError, subprocess.SubprocessError):
                pass

    def _stop_if_current(self, expected: subprocess.Popen) -> None:
        with self._state_lock:
            if self._process is not expected:
                return
            self._process = None
            self._port = None
            self._ready = False
        self._terminate(expected)

    def start(self) -> None:
        with self._state_lock:
            if self._process is not None and self._process.poll() is None:
                process, port = self._process, self._port
                if self._ready:
                    return
            else:
                self._process = None
                self._port = None
                self._ready = False
                if not self.available(self.root):
                    raise WhisperError("whisper_non_disponibile")

                try:
                    port = self._free_loopback_port()
                    command = [
                        str(self.server_path),
                        "-m", str(self.model_path),
                        "-l", LANGUAGE,
                        "--host", "127.0.0.1",
                        "--port", str(port),
                        "--inference-path", INFERENCE_PATH,
                    ]
                    process = subprocess.Popen(
                        command,
                        cwd=str(self.server_path.parent),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except (OSError, ValueError):
                    raise WhisperError("whisper_avvio_non_riuscito") from None

                self._process, self._port = process, port

        deadline = time.monotonic() + self.readiness_timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._stop_if_current(process)
                raise WhisperError("whisper_server_terminato")
            try:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1.0)
                try:
                    connection.request("GET", "/")
                    response = connection.getresponse()
                    response.read(1024)
                    if response.status == 200:
                        with self._state_lock:
                            if self._process is not process or self._port != port:
                                raise WhisperError("whisper_server_non_attivo")
                            self._ready = True
                        return
                finally:
                    connection.close()
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.2)

        self._stop_if_current(process)
        raise WhisperError("whisper_avvio_timeout")

    def transcribe_wav(self, wav_bytes: bytes, *, prompt: str = "") -> str:
        if not isinstance(wav_bytes, bytes) or not wav_bytes:
            raise WhisperError("whisper_audio_non_valido")
        if not isinstance(prompt, str) or len(prompt) > 1200:
            raise WhisperError("whisper_prompt_non_valido")
        if len(wav_bytes) > MAX_WAV_BYTES:
            raise WhisperError("whisper_audio_troppo_grande")
        if len(wav_bytes) < 12 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
            raise WhisperError("whisper_audio_non_valido")
        if not self._inference_lock.acquire(blocking=False):
            raise WhisperBusyError("whisper_busy")

        try:
            with self._state_lock:
                process, port = self._process, self._port
                if process is None or port is None or not self._ready or process.poll() is not None:
                    raise WhisperError("whisper_server_non_attivo")

            boundary = "SalesAgents" + uuid4().hex
            body = bytearray()
            self._add_field(body, boundary, "response_format", "verbose_json")
            if prompt.strip():
                self._add_field(body, boundary, "prompt", prompt.strip())
            body.extend(f"--{boundary}\r\n".encode("ascii"))
            body.extend(b'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n')
            body.extend(b"Content-Type: audio/wav\r\n\r\n")
            body.extend(wav_bytes)
            body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))

            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=self.request_timeout)
            try:
                connection.request("POST", INFERENCE_PATH, body=body, headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body)),
                    "Accept": "application/json",
                    "Connection": "close",
                })
                response = connection.getresponse()
                if response.status != 200:
                    response.read(MAX_RESPONSE_BYTES + 1)
                    raise WhisperError("whisper_richiesta_non_riuscita")
                payload = response.read(MAX_RESPONSE_BYTES + 1)
                if len(payload) > MAX_RESPONSE_BYTES:
                    raise WhisperError("whisper_richiesta_non_riuscita")
            except (OSError, http.client.HTTPException, TimeoutError):
                raise WhisperError("whisper_richiesta_non_riuscita") from None
            finally:
                connection.close()
                body.clear()

            try:
                result = json.loads(payload)
                text = result.get("text") if isinstance(result, dict) else None
                if not isinstance(text, str):
                    raise ValueError
                return text.strip()
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, AttributeError):
                raise WhisperError("whisper_risposta_non_valida") from None
        finally:
            self._inference_lock.release()

    @staticmethod
    def _add_field(body: bytearray, boundary: str, name: str, value: str) -> None:
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"))
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    def stop(self) -> None:
        with self._state_lock:
            process = self._process
            self._process = None
            self._port = None
            self._ready = False
        self._terminate(process)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop()

