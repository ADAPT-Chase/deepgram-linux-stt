# Ops History

## 2026-05-28 01:43:57 — SIGNED_BY_AGENT
Checked post-reboot NoMachine remote STT lag. Verified the service, PipeWire source, Deepgram credentials, and public Voice Agent health were up. Tuned remote STT to Deepgram `nova-3`, 550 ms silence flush, 4-second maximum segment, lower voice threshold, and 8-second provider timeout; added Deepgram latency diagnostics and restart-safe mute state preservation. Restarted `nomachine-remote-stt.service`, added the tuned user unit to `systemd/`, and verified an end-to-end synthetic phrase through the NoMachine audio path was transcribed.

## 2025-11-28 21:45:00
- Started debugging STT application.
- Analyzed logs `stt_debug.log` and `stt_output.log`.
- Identified potential issue with `xdotool` or just log noise.
- Created this history file.
