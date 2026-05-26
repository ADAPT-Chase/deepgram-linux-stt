#!/usr/bin/env python3
"""Continuous local STT for the NoMachine client microphone source."""

from __future__ import annotations

import audioop
import os
import signal
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel


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
    )


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
    print(
        "Remote STT starting "
        f"source={config.source} model={config.model_name} log={config.log_path}",
        flush=True,
    )

    model = WhisperModel(config.model_name, device="cpu", compute_type="int8")
    capture = start_capture(config.source)
    running = True

    def handle_signal(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

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
                if config.type_text:
                    type_transcript(transcript)

    finally:
        stop_capture(capture)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
