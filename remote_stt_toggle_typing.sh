#!/usr/bin/env bash
set -euo pipefail

state_file="${REMOTE_STT_STATE:-/run/user/$(id -u)/remote-stt.state}"
systemctl --user kill --kill-whom=main --signal=SIGUSR1 nomachine-remote-stt.service
sleep 0.1
if [[ -f "${state_file}" ]]; then
    printf 'remote STT typing: %s\n' "$(tr -d '\n' < "${state_file}")"
fi
