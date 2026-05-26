#!/usr/bin/env bash
set -euo pipefail

while IFS='=' read -r key value; do
    case "${key}" in
        DEEPGRAM_API_KEY|DEEPGRAM_API_KEY_nc)
            export "${key}=${value}"
            ;;
    esac
done < /adapt/secrets/m2.env

exec /usr/bin/python3 /adapt/projects/stt/remote_faster_whisper_stt.py
