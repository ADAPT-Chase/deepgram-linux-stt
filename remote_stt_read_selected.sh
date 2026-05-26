#!/usr/bin/env bash
set -euo pipefail

cd /adapt/projects/stt
REMOTE_STT_TTS_CMD="${REMOTE_STT_TTS_CMD:-/data/vast/home/x/.hermes/hermes-agent/venv/bin/edge-tts}" \
REMOTE_STT_TTS_VOICE="${REMOTE_STT_TTS_VOICE:-en-US-AvaMultilingualNeural}" \
python3 - <<'PY'
from remote_faster_whisper_stt import read_selected_text

read_selected_text()
PY
