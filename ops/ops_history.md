# Ops History

## 2026-07-28 17:35:00 — Codex
Completed candidate 3 and stopped its disabled Deepgram GUI backend. The browser microphone route
recognized the operator's words but fragmented, merged, and reformatted utterances, including one
`one two` to `1.2` conversion and two blank segments. Selected Vocalinux
`medium.en-q5_0` for the larger offline test, downloaded the 539,225,533-byte model from the
repository-configured Hugging Face source, and verified SHA-256
`76733e26ad8fe1c7a5bf7531a9d41917b2adc0f20f2e4f5531688a8c6cd88eb0` against the linked object
hash. Launched it alone through the transient benchmark service; Intel Vulkan loaded the model
in 1.93 seconds at approximately 1.0 GB memory. Reasserted both autostart controls as off.

## 2026-07-28 17:31:00 — Codex
Corrected candidate 3 browser launch after the standalone Chrome window closed. Detected the
operator's newly opened logged-in Chrome session, sent the Adapt Dictation URL to that exact
existing browser as a new tab, and activated the window. Verified the visible title is
`Adapt Dictation - Google Chrome` while the raw Deepgram backend remains healthy and listening
on 127.0.0.1:18087.

## 2026-07-28 17:29:00 — Codex
Completed the Vocalinux acceptance test. The offline `small.en-q5_1` model transcribed both
five-word phrases exactly but first injected the false non-speech annotation `(engine revving)`.
Measured local inference at 1.906-1.946 seconds with a two-second silence boundary, approximately
256 MB steady memory, and 584 MB startup peak. Stopped the transient Vocalinux service with both
autostart flags still off. Started only the disabled Deepgram GUI service for raw browser
dictation, verified local health and the 127.0.0.1:18087 listener, and opened the dedicated
`https://dg.adaptdev.ai/dictation` page in Chrome for candidate 3.

## 2026-07-28 17:27:00 — Codex
Completed the first candidate's acceptance phrase with two exact Deepgram transcriptions after
the input repair. The continuously open physical microphone also produced unrelated background
segments, so candidate 1 passes accuracy on clear speech but carries a false-positive and cloud
latency penalty. Stopped and reset the disabled NoMachine STT/audio units. Reconfigured Vocalinux
from `tiny.en-q5_1` to the installed `small.en-q5_1` offline model, kept both autostart controls
off, and launched it alone through a transient `vocalinux-benchmark.service`. Verified the model
loaded on Intel Vulkan in 0.53 seconds with no competing transcriber; startup memory was
approximately 584 MB.

## 2026-07-28 17:25:00 — Codex
Repaired the first isolated dictation candidate after the operator reported no typed output.
The daemon had received three `Ctrl+Space` toggle events and ended in `muted`, while the active
internal microphone was set to 27% (`-34.39 dB`). Restored typing through the supported
`remote-stt-toggle on` path and set the PipeWire input to 60% (`-13.31 dB`) after a 100% signal
probe showed clipping. Verified all three stages independently: a live 16 kHz capture stream,
a successful Deepgram `nova-3` transcript response, and an exact X11 injection result of
`stt-injection-probe-ok`. The daemon remains active only for the isolated test and disabled at
boot.

## 2026-07-28 17:15:00 — Codex
Established a clean transcription benchmark state. Disabled and stopped the Vocalinux login
autostart; the Deepgram GUI and LLM proxy; the NoMachine Deepgram STT and audio shim; the
Pipecat gateway, Switch agent, Hermes agents, and health timer; and the complete `n-voice`
service set, including its memory ingest, timers, and path triggers. Verified that no relevant
processes, capture clients, or TCP listeners survived. Then manually started only
`nomachine-audio-fix.service` and `nomachine-remote-stt.service` as the first isolated candidate;
both remain disabled at boot. The candidate started successfully with Deepgram `nova-3`, typing
enabled, a 650 ms silence boundary, and no competing transcriber. PipeWire verified one live
16 kHz `parec` capture stream from this daemon; with the NoMachine virtual source absent, the
stream is currently bound to the running physical microphone source.

## 2026-06-04 09:27:33 — Veyra, CommsOps - Tier 1 lead
Locked down the local dictation control grammar after live operator validation. Added Deepgram keyterm biasing for `wish`, `voice`, selected-text readback, and spoken navigation phrases; added `enter for next line`, `return for next line`, and `go to next line` as exact Return-key commands in both the browser dictation path and NoMachine daemon path. Verified parser regressions with X11 environment, restarted `deepgram-voice-agent-gui.service` and `nomachine-remote-stt.service`, restored NoMachine typing state to `on`, and confirmed `/api/health` remained OK.

## 2026-06-04 09:06:00 — Veyra, CommsOps - Tier 1 lead
Locked down the live NoMachine dictation grammar after operator validation. Confirmed regression coverage for `wish`/`voice` prefix parity, standalone `enter`/`return`/`next line` Return-key commands, exact selected-text readback commands, and ordinary prose containing `enter` or `return`. Restored the daemon runtime state to `on` after the last `Ctrl+Space` mute event and hardened `remote-stt-toggle` with plain-terminal D-Bus defaults plus deterministic `on` / `off` modes.

## 2026-06-04 08:26:12 — Veyra, CommsOps - Tier 1 lead
Validated and locked down the active NoMachine local dictation controls after live transcription stabilized. Confirmed `Ctrl+Shift+Space` readback, `wish`/`voice` prefix parity, standalone `enter`/`return`/`next line` key commands, and the misheard `re read back selection` path are covered by regression tests. Restored the live daemon state to `on` through `remote_stt_toggle_typing.sh` after finding it muted.

## 2026-06-04 07:58:00 — Veyra, CommsOps - Tier 1 lead
Unmuted the running NoMachine local dictation daemon through its supported `SIGUSR1` toggle path after final verification showed the service processes were active but `/run/user/1000/remote-stt.state` still contained `muted`. Confirmed the state file returned to `on` and both `remote_faster_whisper_stt.py` plus `deepgram_voice_agent_gui.py` remained running.

## 2026-06-04 07:35:41 — Veyra, CommsOps - Tier 1 lead
Hardened local NoMachine dictation controls after live transcription proved usable again. Added real-world STT variants for `voice command`, `wish command`, `press enter`, `press return`, `line break`, `press tab`, `read back the selection`, `readback selection`, and misheard `re read back selection`, while keeping full-segment matching so ordinary prose still types normally. Aligned the installed and tracked `nomachine-remote-stt.service` defaults to typing on and debug skip logging off, cleared the runtime mute state, restarted the user service, and verified the live log started with `typing=on` and captured a fresh transcript row.

## 2026-06-04 06:58:11 — Veyra, CommsOps - Tier 1 lead
Locked browser dictation command handling to match the NoMachine daemon grammar. `voice` and `wish` now work as equivalent exact command prefixes for `enter`, `return`, `next line`, and selected-text readback, while ordinary prose containing those words remains typed text. Added browser parser regression coverage, suppressed the restart-only `audioop` deprecation warning, and verified parser output without typing into the desktop.

## 2026-06-04 06:35:37 — Veyra, CommsOps - Tier 1 lead
Locked down NoMachine dictation command regressions for `wish`/`voice` parity. Added explicit coverage for `wish return`, `wish next line`, and ordinary prose containing `return` so spoken navigation remains command-only while normal dictation remains text.

## 2026-06-04 06:08:03 — Veyra, CommsOps - Tier 1 lead
Added spoken readback controls to the NoMachine local dictation path. `read back selection`, `read selection`, `read selected text`, `read highlighted text`, `read this`, and `read it back` now invoke the same selected-text readback behavior as `Ctrl+Shift+Space` / `remote-stt-read`. The existing `voice` and `wish` command prefixes apply to readback and navigation commands while normal dictation phrases remain text. Added parser regression tests and suppressed the restart-only Python `audioop` deprecation warning.

## 2026-06-04 04:02:24 — Veyra, CommsOps - Tier 1 lead
Locked down local NoMachine dictation command handling. Added standalone spoken key commands for `enter`, `return`, `new line`, `next line`, `new paragraph`, and `tab`, with optional `voice`/`wish` prefixes. Inline spoken punctuation now works for `question mark`, `comma`, `period`, `colon`, `semicolon`, `dash`, and `exclamation point`. Verified parser output without typing into the desktop, restarted `nomachine-remote-stt.service` muted, and documented the local controls/readback path in `README.md`.

## 2026-06-04 03:58:11 — Veyra, CommsOps - Tier 1 lead
Stabilized NoMachine local dictation pause behavior. Muted mode now skips completed audio segments before Deepgram transcription and before text insertion, preventing background audio from generating transcripts or consuming provider calls while paused. Added a 750 ms debounce to Ctrl+Space and SIGUSR1 toggles to prevent repeated hotkey events from flipping state multiple times. Restarted `nomachine-remote-stt.service` muted and verified logs show muted segments being skipped.

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
