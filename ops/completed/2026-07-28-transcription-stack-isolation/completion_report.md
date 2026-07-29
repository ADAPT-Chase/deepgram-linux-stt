# Completion Report

## 2026-07-28 17:15:00 — Codex

The workstation's overlapping transcription and voice stacks were isolated successfully.

- Vocalinux autostart is disabled.
- Deepgram GUI/proxy, Pipecat, `n-voice`, and all associated triggers are disabled and stopped.
- No unrelated NATS or Nova fleet substrate was stopped.
- A zero-listener baseline was verified before testing.
- Only the first candidate, NoMachine Deepgram `nova-3` dictation, was started manually.
- The first candidate remains disabled at boot and can be stopped without altering its config.
- The first candidate has one verified 16 kHz capture stream on the physical PipeWire microphone;
  the NoMachine virtual microphone source is not currently present.
- The initial acceptance attempt failed because typing was toggled to `muted` and microphone gain
  was 27%. Typing is restored, gain is normalized to 60%, Deepgram returned a transcript, and an
  isolated X11 text-injection probe passed exactly.
- Candidate 1 subsequently transcribed the acceptance phrase exactly twice, but its continuously
  open physical-microphone path also emitted unrelated background segments.
- Candidate 2 transcribed both phrases exactly but inserted `(engine revving)` first; its local
  inference was about 1.91 seconds with a two-second silence boundary.
- Candidates 1 and 2 are stopped. Candidate 3 is the only active transcription backend and is
  exposed through the raw Deepgram browser-dictation page with LLM polish disabled.
- Candidate 3 is open as an active tab in the operator's existing logged-in Chrome session after
  the separate benchmark window closed.
- Candidate 3 showed split, merged, reformatted, and blank segments and is now stopped.
- Candidate 4 is Vocalinux `medium.en-q5_0`, loaded alone on Intel Vulkan from a checksum-verified
  539,225,533-byte model at approximately 1.0 GB memory.
- Candidate 4 achieved the best normalized accuracy but short chunks ran slower than real time
  and created delayed partial/full duplicates through the uncancelled inference queue.
- Final baseline: every tested transcription, Pipecat, and `n-voice` component is stopped and
  disabled; no relevant capture process or listener remains.
- Candidate 5 is staged alone with Vosk small using a verified 68 MB English model at
  approximately 206 MB loaded memory; its live acceptance result is pending.

Recommended comparison order:

1. NoMachine Deepgram `nova-3` direct dictation.
2. Vocalinux using the installed `small.en-q5_1` model for a fair quality test.
3. Browser Deepgram `nova-3` dictation if NoMachine microphone transport is unstable.
4. `n-voice` plus Pipecat only for end-to-end conversational agent evaluation.
