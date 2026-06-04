#!/usr/bin/env bash
set -euo pipefail

state_file="${REMOTE_STT_STATE:-/run/user/$(id -u)/remote-stt.state}"
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export XDG_RUNTIME_DIR="${runtime_dir}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${runtime_dir}/bus}"

mode="${1:-toggle}"
if [[ "${mode}" != "toggle" && "${mode}" != "on" && "${mode}" != "off" ]]; then
    printf 'usage: %s [toggle|on|off]\n' "${0##*/}" >&2
    exit 2
fi

current_state() {
    if [[ ! -f "${state_file}" ]]; then
        printf 'unknown'
        return
    fi

    case "$(tr -d '\n' < "${state_file}")" in
        on|true|1|enabled|unmuted) printf 'on' ;;
        *) printf 'muted' ;;
    esac
}

if [[ "${mode}" == "on" && "$(current_state)" == "on" ]]; then
    printf 'remote STT typing: on\n'
    exit 0
fi

if [[ "${mode}" == "off" && "$(current_state)" == "muted" ]]; then
    printf 'remote STT typing: muted\n'
    exit 0
fi

send_toggle() {
    systemctl --user kill --kill-whom=main --signal=SIGUSR1 nomachine-remote-stt.service
    sleep "${REMOTE_STT_TOGGLE_SETTLE_S:-0.2}"
}

send_toggle

if [[ "${mode}" == "on" && "$(current_state)" != "on" ]]; then
    sleep "${REMOTE_STT_DEBOUNCE_S:-0.85}"
    send_toggle
elif [[ "${mode}" == "off" && "$(current_state)" != "muted" ]]; then
    sleep "${REMOTE_STT_DEBOUNCE_S:-0.85}"
    send_toggle
fi

if [[ -f "${state_file}" ]]; then
    printf 'remote STT typing: %s\n' "$(tr -d '\n' < "${state_file}")"
fi
