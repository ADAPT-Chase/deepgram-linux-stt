#!/usr/bin/env python3
"""Continuous local STT for the NoMachine client microphone source."""

from __future__ import annotations

import audioop
import os
import io
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
import tempfile
import wave
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

signal.signal(signal.SIGUSR1, signal.SIG_IGN)

import requests
from pynput import keyboard

if TYPE_CHECKING:
    from faster_whisper import WhisperModel


SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
CHUNK_MS = 100
CHUNK_BYTES = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES * CHUNK_MS // 1000
READBACK_ACTIVE = threading.Event()
TTS_PROCESS_LOCK = threading.Lock()
TTS_PROCESS: subprocess.Popen[bytes] | None = None


@dataclass(frozen=True)
class SttConfig:
    """Runtime configuration for remote microphone transcription."""

    source: str
    provider: str
    model_name: str
    deepgram_model: str
    deepgram_key_envs: tuple[str, ...]
    deepgram_timeout_s: float
    local_fallback: bool
    log_path: Path
    threshold: int
    silence_ms: int
    min_speech_ms: int
    max_segment_ms: int
    beam_size: int
    vad_filter: bool
    condition_on_previous_text: bool
    no_speech_threshold: float
    type_text: bool
    hotkey_enabled: bool
    state_path: Path
    readback_enabled: bool
    readback_max_chars: int
    tts_command: str
    tts_voice: str
    debug: bool


def load_config() -> SttConfig:
    """Load STT configuration from environment variables."""

    return SttConfig(
        source=os.getenv("REMOTE_STT_SOURCE", "nx_client_mic"),
        provider=os.getenv("REMOTE_STT_PROVIDER", "local"),
        model_name=os.getenv("REMOTE_STT_MODEL", "tiny.en"),
        deepgram_model=os.getenv("REMOTE_STT_DEEPGRAM_MODEL", "nova-3"),
        deepgram_key_envs=tuple(
            key.strip()
            for key in os.getenv(
                "REMOTE_STT_DEEPGRAM_KEY_ENVS",
                "DEEPGRAM_API_KEY,DEEPGRAM_API_KEY_nc",
            ).split(",")
            if key.strip()
        ),
        deepgram_timeout_s=float(os.getenv("REMOTE_STT_DEEPGRAM_TIMEOUT_S", "12")),
        local_fallback=os.getenv("REMOTE_STT_LOCAL_FALLBACK", "0") == "1",
        log_path=Path(
            os.getenv("REMOTE_STT_LOG", "/adapt/projects/stt/remote_transcriptions.txt")
        ),
        threshold=int(os.getenv("REMOTE_STT_THRESHOLD", "350")),
        silence_ms=int(os.getenv("REMOTE_STT_SILENCE_MS", "900")),
        min_speech_ms=int(os.getenv("REMOTE_STT_MIN_SPEECH_MS", "500")),
        max_segment_ms=int(os.getenv("REMOTE_STT_MAX_SEGMENT_MS", "12000")),
        beam_size=int(os.getenv("REMOTE_STT_BEAM_SIZE", "1")),
        vad_filter=os.getenv("REMOTE_STT_VAD_FILTER", "1") == "1",
        condition_on_previous_text=os.getenv("REMOTE_STT_CONDITION_PREVIOUS", "0") == "1",
        no_speech_threshold=float(os.getenv("REMOTE_STT_NO_SPEECH_THRESHOLD", "0.6")),
        type_text=os.getenv("REMOTE_STT_TYPE_TEXT", "0") == "1",
        hotkey_enabled=os.getenv("REMOTE_STT_HOTKEY", "ctrl+space") != "off",
        state_path=Path(
            os.getenv("REMOTE_STT_STATE", f"/run/user/{os.getuid()}/remote-stt.state")
        ),
        readback_enabled=os.getenv("REMOTE_STT_READBACK", "1") == "1",
        readback_max_chars=int(os.getenv("REMOTE_STT_READBACK_MAX_CHARS", "1200")),
        tts_command=os.getenv(
            "REMOTE_STT_TTS_CMD",
            "/data/vast/home/x/.hermes/hermes-agent/venv/bin/edge-tts",
        ),
        tts_voice=os.getenv("REMOTE_STT_TTS_VOICE", "en-US-AvaMultilingualNeural"),
        debug=os.getenv("REMOTE_STT_DEBUG", "0") == "1",
    )


class HotkeyController:
    """Thread-safe STT controls with typing and readback hotkeys."""

    def __init__(self, enabled: bool, state_path: Path, readback_enabled: bool) -> None:
        self._state_path = state_path
        self._readback_enabled = readback_enabled
        self._lock = threading.Lock()
        self._pressed: set[keyboard.Key | keyboard.KeyCode] = set()
        self._enabled = self._read_state(default=enabled)
        self._write_state(self._enabled)

    def enabled(self) -> bool:
        """Return whether recognized text should be typed into the active window."""

        with self._lock:
            return self._enabled

    def toggle(self) -> bool:
        """Toggle text injection and return the new state."""

        with self._lock:
            self._enabled = not self._enabled
            enabled = self._enabled

        state = "unmuted" if enabled else "muted"
        print(f"Remote STT typing {state}", flush=True)
        self._write_state(enabled)
        notify_state(enabled)
        return enabled

    def on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        """Handle global key presses for Ctrl+Space mute toggling."""

        with self._lock:
            if key in self._pressed:
                return
            self._pressed.add(key)

            ctrl_down = self._ctrl_down()
            shift_down = self._shift_down()
            if ctrl_down and shift_down and key == keyboard.Key.space:
                readback = self._readback_enabled
                enabled = None
            elif ctrl_down and not shift_down and key == keyboard.Key.space:
                self._enabled = not self._enabled
                enabled = self._enabled
                readback = False
            else:
                enabled = None
                readback = False

        if enabled is not None:
            state = "unmuted" if enabled else "muted"
            print(f"Remote STT typing {state} by Ctrl+Space", flush=True)
            self._write_state(enabled)
            notify_state(enabled)
        elif readback:
            threading.Thread(target=read_selected_text, daemon=True).start()
        elif ctrl_down and shift_down and key == keyboard.Key.space:
            notify_message("NoMachine remote STT", "Readback disabled")

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        """Track key releases for hotkey debounce."""

        with self._lock:
            self._pressed.discard(key)

    def _write_state(self, enabled: bool) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text("on\n" if enabled else "muted\n", encoding="utf-8")

    def _read_state(self, default: bool) -> bool:
        try:
            value = self._state_path.read_text(encoding="utf-8").strip().lower()
        except OSError:
            return default
        return value in {"on", "true", "1", "enabled", "unmuted"}

    def _ctrl_down(self) -> bool:
        return (
            keyboard.Key.ctrl in self._pressed
            or keyboard.Key.ctrl_l in self._pressed
            or keyboard.Key.ctrl_r in self._pressed
        )

    def _shift_down(self) -> bool:
        return (
            keyboard.Key.shift in self._pressed
            or keyboard.Key.shift_l in self._pressed
            or keyboard.Key.shift_r in self._pressed
        )


def notify_state(enabled: bool) -> None:
    """Show a desktop notification for the current typing state if available."""

    state = "Typing ON" if enabled else "Typing MUTED"
    subprocess.run(
        ["notify-send", "-t", "1200", "NoMachine remote STT", state],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def read_selected_text() -> None:
    """Read highlighted text aloud using the X11 selection or clipboard fallback."""

    if READBACK_ACTIVE.is_set():
        stop_speech()
        READBACK_ACTIVE.clear()
        notify_message("NoMachine remote STT", "Readback stopped")
        print("Remote STT readback stopped", flush=True)
        return

    notify_message("NoMachine remote STT", "Reading selected text")
    text = selected_text()
    if not text:
        notify_message("NoMachine remote STT", "No selected text found")
        print("Remote STT readback: no selected text found", flush=True)
        return

    max_chars = int(os.getenv("REMOTE_STT_READBACK_MAX_CHARS", "1200"))
    text = " ".join(text.split())[:max_chars]
    print(f"Remote STT readback: {len(text)} chars", flush=True)
    speak_text(text)


def selected_text() -> str:
    """Return highlighted X11 text without requiring xclip/xsel."""

    text = primary_selection_text()
    if text:
        return text
    return clipboard_selection_text()


def primary_selection_text() -> str:
    """Read the X11 PRIMARY selection, which usually tracks highlighted text."""

    root = None
    try:
        root = tk.Tk()
        root.withdraw()
        return root.selection_get(selection="PRIMARY").strip()
    except Exception:
        return ""
    finally:
        if root is not None:
            root.destroy()


def clipboard_selection_text() -> str:
    """Copy selected text, read the clipboard, then restore the previous clipboard."""

    root = None
    previous = ""
    try:
        root = tk.Tk()
        root.withdraw()
        try:
            previous = root.clipboard_get()
        except Exception:
            previous = ""

        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", "ctrl+c"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.15)

        try:
            copied = root.clipboard_get().strip()
        except Exception:
            copied = ""

        root.clipboard_clear()
        if previous:
            root.clipboard_append(previous)
        root.update()
        return copied if copied != previous else ""
    finally:
        if root is not None:
            root.destroy()


def speak_text(text: str) -> None:
    """Speak text with Edge neural TTS when available, otherwise speech-dispatcher."""

    if not text:
        return

    READBACK_ACTIVE.set()
    try:
        command = os.getenv(
            "REMOTE_STT_TTS_CMD",
            "/data/vast/home/x/.hermes/hermes-agent/venv/bin/edge-tts",
        )
        if command.endswith("edge-tts"):
            speak_with_edge_tts(command, text)
        elif command == "spd-say":
            run_tts_process(["spd-say", "--wait", text])
        else:
            run_tts_process(["espeak", text])
    finally:
        READBACK_ACTIVE.clear()


def speak_with_edge_tts(command: str, text: str) -> None:
    """Generate speech with Edge neural TTS and play it through PipeWire/Pulse."""

    voice = os.getenv("REMOTE_STT_TTS_VOICE", "en-US-AvaMultilingualNeural")
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as media:
        media_path = Path(media.name)

    try:
        synth = subprocess.run(
            [
                command,
                "--voice",
                voice,
                "--text",
                text,
                "--write-media",
                str(media_path),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if synth.returncode != 0:
            print(
                f"Edge TTS failed, falling back to spd-say: {synth.stderr.strip()}",
                file=sys.stderr,
                flush=True,
            )
            run_tts_process(["spd-say", "--wait", text])
            return

        player_command = (
            f"ffmpeg -nostdin -loglevel error -i {str(media_path)!r} "
            "-f s16le -ar 24000 -ac 1 - | "
            "pacat --playback --raw --format=s16le --rate=24000 --channels=1"
        )
        run_tts_process(["bash", "-lc", player_command])
    finally:
        media_path.unlink(missing_ok=True)


def run_tts_process(command: list[str]) -> None:
    """Run one TTS/playback process, replacing any previous readback."""

    global TTS_PROCESS
    stop_speech()
    with TTS_PROCESS_LOCK:
        TTS_PROCESS = subprocess.Popen(command)
        process = TTS_PROCESS

    try:
        process.wait(timeout=90)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=3)
    finally:
        with TTS_PROCESS_LOCK:
            if TTS_PROCESS is process:
                TTS_PROCESS = None


def stop_speech() -> None:
    """Stop active readback playback."""

    global TTS_PROCESS
    with TTS_PROCESS_LOCK:
        process = TTS_PROCESS
        TTS_PROCESS = None

    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def notify_message(title: str, message: str) -> None:
    """Show a desktop notification when notify-send is available."""

    subprocess.run(
        ["notify-send", "-t", "1200", title, message],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_hotkey_listener(controller: HotkeyController) -> keyboard.Listener | None:
    """Start desktop hotkeys when the X session is reachable."""

    try:
        listener = keyboard.Listener(
            on_press=controller.on_press,
            on_release=controller.on_release,
        )
        listener.start()
        print(
            "Remote STT hotkeys enabled: Ctrl+Space toggles typing; "
            "Ctrl+Shift+Space reads selected text",
            flush=True,
        )
        return listener
    except Exception as exc:
        print(f"Remote STT hotkey unavailable: {exc}", file=sys.stderr, flush=True)
        return None


def start_capture(source: str) -> subprocess.Popen[bytes]:
    """Start raw PCM capture from a PulseAudio/PipeWire source."""

    command = [
        "parec",
        f"--device={source}",
        "--format=s16le",
        f"--rate={SAMPLE_RATE}",
        f"--channels={CHANNELS}",
        "--latency-msec=50",
    ]
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def transcribe_audio(model: "WhisperModel | None", pcm: bytes, config: SttConfig) -> str:
    """Transcribe signed 16-bit mono PCM bytes with the configured provider."""

    if config.provider == "deepgram":
        transcript = transcribe_with_deepgram(pcm, config)
        if transcript:
            return transcript
        if not config.local_fallback:
            return ""
        print("Deepgram returned no transcript; falling back to local STT", flush=True)

    if model is None:
        from faster_whisper import WhisperModel

        model = WhisperModel(config.model_name, device="cpu", compute_type="int8")

    if model is None:
        return ""

    return transcribe_with_faster_whisper(model, pcm, config)


def transcribe_with_faster_whisper(
    model: "WhisperModel",
    pcm: bytes,
    config: SttConfig,
) -> str:
    """Transcribe signed 16-bit mono PCM bytes with faster-whisper."""

    if not pcm:
        return ""

    import numpy as np

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        return ""

    segments, _info = model.transcribe(
        samples,
        beam_size=config.beam_size,
        language="en",
        vad_filter=config.vad_filter,
        condition_on_previous_text=config.condition_on_previous_text,
        no_speech_threshold=config.no_speech_threshold,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def transcribe_with_deepgram(pcm: bytes, config: SttConfig) -> str:
    """Transcribe signed 16-bit mono PCM bytes with Deepgram prerecorded STT."""

    if not pcm:
        return ""

    wav_bytes = pcm_to_wav_bytes(pcm)
    url = "https://api.deepgram.com/v1/listen"
    params = {
        "model": config.deepgram_model,
        "language": "en-US",
        "smart_format": "true",
        "punctuate": "true",
        "dictation": "true",
        "paragraphs": "false",
        "utterances": "false",
    }
    headers = {"Content-Type": "audio/wav"}

    for key_env in config.deepgram_key_envs:
        api_key = os.getenv(key_env)
        if not api_key:
            continue

        try:
            started_at = time.monotonic()
            response = requests.post(
                url,
                params=params,
                headers={**headers, "Authorization": f"Token {api_key}"},
                data=wav_bytes,
                timeout=(3.05, config.deepgram_timeout_s),
            )
        except requests.RequestException as exc:
            print(f"Deepgram request failed via {key_env}: {exc}", file=sys.stderr, flush=True)
            continue

        elapsed_ms = (time.monotonic() - started_at) * 1000
        if elapsed_ms >= 1500:
            audio_ms = len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES) * 1000
            print(
                f"Deepgram STT latency {elapsed_ms:.0f} ms via {key_env} "
                f"status={response.status_code} audio_ms={audio_ms:.0f}",
                flush=True,
            )

        if response.status_code in {401, 402, 403, 429}:
            print(
                f"Deepgram key {key_env} rejected with HTTP {response.status_code}; trying next key",
                file=sys.stderr,
                flush=True,
            )
            continue

        if response.status_code >= 400:
            print(
                f"Deepgram request failed with HTTP {response.status_code}",
                file=sys.stderr,
                flush=True,
            )
            continue

        try:
            payload = response.json()
            channels = payload["results"]["channels"]
            alternatives = channels[0]["alternatives"]
            transcript = alternatives[0].get("transcript", "")
            return transcript.strip()
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            print(f"Deepgram response parse failed: {exc}", file=sys.stderr, flush=True)
            return ""

    return ""


def pcm_to_wav_bytes(pcm: bytes) -> bytes:
    """Wrap raw signed 16-bit mono PCM bytes in a WAV container."""

    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(CHANNELS)
        wav_file.setsampwidth(SAMPLE_WIDTH_BYTES)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(pcm)
    return output.getvalue()


def append_transcript(log_path: Path, transcript: str) -> None:
    """Append a timestamped transcript to disk and stdout."""

    if not transcript:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {transcript}"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")
    print(line, flush=True)


def type_transcript(transcript: str) -> None:
    """Optionally type recognized text into the active X11 window."""

    if not transcript:
        return

    subprocess.run(
        ["xdotool", "type", "--clearmodifiers", "--delay", "10", f"{transcript} "],
        check=False,
    )


def stop_capture(process: subprocess.Popen[bytes]) -> None:
    """Terminate the capture process."""

    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def main() -> int:
    """Run continuous speech segmentation and transcription."""

    config = load_config()
    hotkey_controller = HotkeyController(
        enabled=config.type_text,
        state_path=config.state_path,
        readback_enabled=config.readback_enabled,
    )
    model_label = config.deepgram_model if config.provider == "deepgram" else config.model_name
    print(
        "Remote STT starting "
        f"source={config.source} provider={config.provider} model={model_label} "
        f"log={config.log_path} typing={'on' if hotkey_controller.enabled() else 'muted'} "
        f"state={config.state_path}",
        flush=True,
    )
    print(
        "Remote STT segmentation "
        f"threshold={config.threshold} silence_ms={config.silence_ms} "
        f"min_speech_ms={config.min_speech_ms} max_segment_ms={config.max_segment_ms} "
            f"deepgram_timeout_s={config.deepgram_timeout_s:g}",
        flush=True,
    )

    model: "WhisperModel | None" = None
    if config.provider != "deepgram" or config.local_fallback:
        from faster_whisper import WhisperModel

        model = WhisperModel(config.model_name, device="cpu", compute_type="int8")
    capture = start_capture(config.source)
    listener = start_hotkey_listener(hotkey_controller) if config.hotkey_enabled else None
    running = True

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    def toggle_typing(_signum: int, _frame: object) -> None:
        hotkey_controller.toggle()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGUSR1, toggle_typing)

    speech = bytearray()
    pre_roll: deque[bytes] = deque(maxlen=max(1, 300 // CHUNK_MS))
    silence_chunks = 0
    speech_chunks = 0
    peak_rms = 0

    try:
        if capture.stdout is None:
            print("Capture process did not expose stdout", file=sys.stderr, flush=True)
            return 1

        while running:
            chunk = capture.stdout.read(CHUNK_BYTES)
            if not chunk:
                stderr = capture.stderr.read().decode("utf-8", errors="replace") if capture.stderr else ""
                print(f"Capture ended unexpectedly: {stderr.strip()}", file=sys.stderr, flush=True)
                return 1

            if READBACK_ACTIVE.is_set():
                speech.clear()
                pre_roll.clear()
                silence_chunks = 0
                speech_chunks = 0
                peak_rms = 0
                continue

            rms = audioop.rms(chunk, SAMPLE_WIDTH_BYTES)
            peak_rms = max(peak_rms, rms)
            has_voice = rms >= config.threshold

            if not speech:
                pre_roll.append(chunk)
                if not has_voice:
                    continue
                speech.extend(b"".join(pre_roll))
                pre_roll.clear()

            speech.extend(chunk)
            speech_chunks += 1

            if has_voice:
                silence_chunks = 0
            else:
                silence_chunks += 1

            segment_ms = speech_chunks * CHUNK_MS
            should_flush = (
                silence_chunks * CHUNK_MS >= config.silence_ms
                and segment_ms >= config.min_speech_ms
            ) or segment_ms >= config.max_segment_ms

            if should_flush:
                pcm = bytes(speech)
                audio_ms = len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES) * 1000
                segment_peak_rms = peak_rms
                speech.clear()
                speech_chunks = 0
                silence_chunks = 0
                peak_rms = 0

                transcript = transcribe_audio(model, pcm, config)
                if config.debug:
                    print(
                        "Remote STT segment "
                        f"audio_ms={audio_ms:.0f} peak_rms={segment_peak_rms} "
                        f"transcript_len={len(transcript)}",
                        flush=True,
                    )
                append_transcript(config.log_path, transcript)
                if hotkey_controller.enabled():
                    type_transcript(transcript)

    finally:
        if listener is not None:
            listener.stop()
        stop_capture(capture)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
