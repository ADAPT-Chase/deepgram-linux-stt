# Ops History

## 2026-05-28 02:33:44 — SIGNED_BY_AGENT
Fixed garbled dictation caused by two active transcription typers. Disabled and stopped the legacy `nomachine-remote-stt.service`, changed browser dictation to serialize text insertion, and switched the preferred insertion method from slow per-character `xdotool type` to clipboard paste with terminal-aware paste keys. Restarted `deepgram-voice-agent-gui.service` and verified the dictation WebSocket still transcribes a synthetic phrase with typing disabled.

## 2026-05-28 02:21:29 — SIGNED_BY_AGENT
Investigated continued remote transcription failure. Found NoMachine virtual microphone sources were silent after reboot even though the session accepted a voice server connection. Added browser-microphone dictation at `/dictation` with `/ws/dictate`; the browser sends 16 kHz PCM, the server transcribes through Deepgram `nova-3`, and recognized text is typed into the active X11 window through `xdotool`. Restarted `deepgram-voice-agent-gui.service` and verified a synthetic WebSocket dictation phrase with typing disabled.

## 2026-05-28 01:43:57 — SIGNED_BY_AGENT
Checked post-reboot NoMachine remote STT lag. Verified the service, PipeWire source, Deepgram credentials, and public Voice Agent health were up. Tuned remote STT to Deepgram `nova-3`, 550 ms silence flush, 4-second maximum segment, lower voice threshold, and 8-second provider timeout; added Deepgram latency diagnostics and restart-safe mute state preservation. Restarted `nomachine-remote-stt.service`, added the tuned user unit to `systemd/`, and verified an end-to-end synthetic phrase through the NoMachine audio path was transcribed.

## 2025-11-28 21:45:00
- Started debugging STT application.
- Analyzed logs `stt_debug.log` and `stt_output.log`.
- Identified potential issue with `xdotool` or just log noise.
- Created this history file.
