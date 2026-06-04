# Ops History

## 2026-06-04 03:53:01 — Veyra, CommsOps - Tier 1 lead
Restored local NoMachine dictation through `nomachine-remote-stt.service`. The installed user service now matches the tracked Deepgram-only path with no local Whisper fallback, active GDM Xauthority for `xdotool`, typing enabled by default, and tuned segmentation for low-latency desktop dictation. Restarted and enabled the service; live status showed active capture from `nx_client_mic`, about 35 MB startup memory, and successful live transcript segments. Added PATH helpers `remote-stt-toggle` and `remote-stt-read`.

## 2026-06-04 03:30:16 — Veyra, CommsOps - Tier 1 lead
Restarted `deepgram-voice-agent-gui.service` with dictation polish disabled. Verified the live process environment reports `VOICE_AGENT_DICTATION_POLISH=0` and `VOICE_AGENT_DICTATION_POLISH_READ_TIMEOUT=2`. Ran a muted synthetic `/ws/dictate` WebSocket test with generated speech; Deepgram returned "Testing dictation latency" and the route completed in 622 ms without typing into the active desktop window.

## 2026-06-04 03:29:05 — Veyra, CommsOps - Tier 1 lead
Disabled the browser dictation LLM polish pass in the installed user service and tracked systemd template. Reduced the polish read timeout from 15 seconds to 2 seconds as a guard if polish is re-enabled later. This keeps `/dictation` on Deepgram Nova-3 raw typing and removes the post-transcription stall that matched the observed lag.

## 2026-05-28 06:42:23 — sable
Investigated voice-agent no-audio playback. A direct WebSocket smoke test using the current Deepgram `InjectUserMessage` format returned assistant text plus 38 PCM audio frames / 36480 bytes, so the backend Voice Agent + TTS path is functional. Fixed the GUI typed-turn payload, added a Test Sound button, added audio frame/byte logging on `AgentAudioDone`, added Blob-to-ArrayBuffer fallback, increased playback gain, restarted `deepgram-voice-agent-gui.service`, and verified the public page serves the updated client.

## 2026-05-28 05:37:09 — sable
Added optional LLM-backed cleanup for `/dictation`. Completed STT segments now pass through the configured bearer-auth OpenAI-compatible LLM endpoint when `VOICE_AGENT_DICTATION_POLISH=1`, with cleanup constrained to punctuation, capitalization, paragraph formatting, and obvious duplicate words. Spoken key commands skip the LLM path. Installed the updated user systemd unit, restarted `deepgram-voice-agent-gui.service`, verified live service environment, verified `/dictation` delivery, and smoke-tested the cleanup route through `https://dg.adaptdev.ai/v1/chat/completions`.

## 2026-05-28 05:24:50 — sable
Added spoken mute/unmute controls to `/dictation`. The browser-microphone path now treats `mute`, `mute on`, `typing off`, `dictation off`, and `stop typing` as commands to keep listening while suppressing text insertion, and treats `unmute`, `mute off`, `typing on`, `dictation on`, and `start typing` as commands to resume insertion. Updated README command notes and verified parser behavior, page delivery, and service state.

## 2026-05-28 05:17:36 — sable
Replaced legacy placeholder signature tokens with `sable` in the Deepgram STT project ops files per operator request.

## 2026-05-28 05:13:25 — sable
Added spoken command handling to `/dictation`. The server now converts spoken `enter`, `return`, `new line`, `new paragraph`, `tab`, and punctuation commands into `xdotool` actions before typing. Added command keyterms for Deepgram Nova-3, restarted `deepgram-voice-agent-gui.service`, verified parser output for mixed commands, and documented the supported spoken commands in README.

## 2026-05-28 05:07:10 — sable
Tuned `/dictation` for complete utterances and single-word captures. Increased silence flush to 1100 ms, lowered minimum speech duration to 120 ms, extended maximum segments to 6 seconds, increased pre-roll to 500 ms, and added Nova-3 `keyterm` prompting for Adapt/Nova vocabulary including `autonomous`. Restarted `deepgram-voice-agent-gui.service` and verified synthetic single-word transcription.

## 2026-05-28 03:11:25 — sable
Removed clipboard paste from browser dictation because it triggered Codex/browser “Failed to paste image” clipboard errors. Browser dictation now uses only serialized direct `xdotool type` with a short delay. Restarted `deepgram-voice-agent-gui.service`, confirmed the legacy NoMachine STT daemon remains disabled/inactive, and verified synthetic WebSocket transcription with typing disabled.

## 2026-05-28 02:33:44 — sable
Fixed garbled dictation caused by two active transcription typers. Disabled and stopped the legacy `nomachine-remote-stt.service`, changed browser dictation to serialize text insertion, and switched the preferred insertion method from slow per-character `xdotool type` to clipboard paste with terminal-aware paste keys. Restarted `deepgram-voice-agent-gui.service` and verified the dictation WebSocket still transcribes a synthetic phrase with typing disabled.

## 2026-05-28 02:21:29 — sable
Investigated continued remote transcription failure. Found NoMachine virtual microphone sources were silent after reboot even though the session accepted a voice server connection. Added browser-microphone dictation at `/dictation` with `/ws/dictate`; the browser sends 16 kHz PCM, the server transcribes through Deepgram `nova-3`, and recognized text is typed into the active X11 window through `xdotool`. Restarted `deepgram-voice-agent-gui.service` and verified a synthetic WebSocket dictation phrase with typing disabled.

## 2026-05-28 01:43:57 — sable
Checked post-reboot NoMachine remote STT lag. Verified the service, PipeWire source, Deepgram credentials, and public Voice Agent health were up. Tuned remote STT to Deepgram `nova-3`, 550 ms silence flush, 4-second maximum segment, lower voice threshold, and 8-second provider timeout; added Deepgram latency diagnostics and restart-safe mute state preservation. Restarted `nomachine-remote-stt.service`, added the tuned user unit to `systemd/`, and verified an end-to-end synthetic phrase through the NoMachine audio path was transcribed.

## 2025-11-28 21:45:00
- Started debugging STT application.
- Analyzed logs `stt_debug.log` and `stt_output.log`.
- Identified potential issue with `xdotool` or just log noise.
- Created this history file.
