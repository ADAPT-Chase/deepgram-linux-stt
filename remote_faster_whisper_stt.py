#!/usr/bin/env python3
"""Continuous local STT for the NoMachine client microphone source."""

from __future__ import annotations

import audioop
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

signal.signal(signal.SIGUSR1, signal.SIG_IGN)

import numpy as np
from faster_whisper import WhisperModel
from pynput import keyboard


SAMPLE_RATE = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
CHUNK_MS = 100
CHUNK_BYTES = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH_BYTES * CHUNK_MS // 1000


@dataclass(frozen=True)
class SttConfig:
    """Runtime configuration for remote microphone transcription."""

    source: str
    model_name: str
    log_path: Path
    threshold: int
    silence_ms: int
    min_speech_ms: int
    max_segment_ms: int
    type_text: bool
    hotkey_enabled: bool
    state_path: Path


def load_config() -> SttConfig:
    """Load STT configuration from environment variables."""

    return SttConfig(
        source=os.getenv("REMOTE_STT_SOURCE", "nx_client_mic"),
        model_name=os.getenv("REMOTE_STT_MODEL", "tiny.en"),
        log_path=Path(
            os.getenv("REMOTE_STT_LOG", "/adapt/projects/stt/remote_transcriptions.txt")
        ),
        threshold=int(os.getenv("REMOTE_STT_THRESHOLD", "350")),
        silence_ms=int(os.getenv("REMOTE_STT_SILENCE_MS", "900")),
        min_speech_ms=int(os.getenv("REMOTE_STT_MIN_SPEECH_MS", "500")),
        max_segment_ms=int(os.getenv("REMOTE_STT_MAX_SEGMENT_MS", "12000")),
        type_text=os.getenv("REMOTE_STT_TYPE_TEXT", "0") == "1",
        hotkey_enabled=os.getenv("REMOTE_STT_HOTKEY", "ctrl+space") != "off",
        state_path=Path(
            os.getenv("REMOTE_STT_STATE", f"/run/user/{os.getuid()}/remote-stt.state")
        ),
    )


class TypingController:
    """Thread-safe text injection gate with hotkey and signal toggles."""

    def __init__(self, enabled: bool, state_path: Path) -> None:
        self._enabled = enabled
        self._state_path = state_path
        self._lock = threading.Lock()
        self._pressed: set[keyboard.Key | keyboard.KeyCode] = set()
        self._write_state(enabled)

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

            ctrl_down = (
                keyboard.Key.ctrl in self._pressed
                or keyboard.Key.ctrl_l in self._pressed
                or keyboard.Key.ctrl_r in self._pressed
            )
            if ctrl_down and key == keyboard.Key.space:
                self._enabled = not self._enabled
                enabled = self._enabled
            else:
                enabled = None

        if enabled is not None:
            state = "unmuted" if enabled else "muted"
            print(f"Remote STT typing {state} by Ctrl+Space", flush=True)
            self._write_state(enabled)
            notify_state(enabled)

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        """Track key releases for hotkey debounce."""

        with self._lock:
            self._pressed.discard(key)

    def _write_state(self, enabled: bool) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text("on\n" if enabled else "muted\n", encoding="utf-8")


def notify_state(enabled: bool) -> None:
    """Show a desktop notification for the current typing state if available."""

    state = "Typing ON" if enabled else "Typing MUTED"
    subprocess.run(
        ["notify-send", "-t", "1200", "NoMachine remote STT", state],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_hotkey_listener(controller: TypingController) -> keyboard.Listener | None:
    """Start the Ctrl+Space hotkey listener when the X session is reachable."""

    try:
        listener = keyboard.Listener(
            on_press=controller.on_press,
            on_release=controller.on_release,
        )
        listener.start()
        print("Remote STT hotkey enabled: Ctrl+Space toggles typing", flush=True)
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


def transcribe_audio(model: WhisperModel, pcm: bytes) -> str:
    """Transcribe signed 16-bit mono PCM bytes with faster-whisper."""

    if not pcm:
        return ""

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if samples.size == 0:
        return ""

    segments, _info = model.transcribe(
        samples,
        beam_size=1,
        language="en",
        vad_filter=True,
        condition_on_previous_text=False,
        no_speech_threshold=0.6,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


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
    typing_controller = TypingController(
        enabled=config.type_text,
        state_path=config.state_path,
    )
    print(
        "Remote STT starting "
        f"source={config.source} model={config.model_name} log={config.log_path} "
        f"typing={'on' if config.type_text else 'muted'} state={config.state_path}",
        flush=True,
    )

    model = WhisperModel(config.model_name, device="cpu", compute_type="int8")
    capture = start_capture(config.source)
    listener = start_hotkey_listener(typing_controller) if config.hotkey_enabled else None
    running = True

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    def toggle_typing(_signum: int, _frame: object) -> None:
        typing_controller.toggle()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGUSR1, toggle_typing)

    speech = bytearray()
    pre_roll: deque[bytes] = deque(maxlen=max(1, 300 // CHUNK_MS))
    silence_chunks = 0
    speech_chunks = 0

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

            rms = audioop.rms(chunk, SAMPLE_WIDTH_BYTES)
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
                speech.clear()
                speech_chunks = 0
                silence_chunks = 0

                transcript = transcribe_audio(model, pcm)
                append_transcript(config.log_path, transcript)
                if typing_controller.enabled():
                    type_transcript(transcript)

    finally:
        if listener is not None:
            listener.stop()
        stop_capture(capture)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
