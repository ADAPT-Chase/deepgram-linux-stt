#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from remote_faster_whisper_stt import read_selected_text

read_selected_text()
PY
