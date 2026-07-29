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
- Candidate 1 is stopped and candidate 2 is running alone as a transient Vocalinux service using
  the offline `small.en-q5_1` model on Intel Vulkan.

Recommended comparison order:

1. NoMachine Deepgram `nova-3` direct dictation.
2. Vocalinux using the installed `small.en-q5_1` model for a fair quality test.
3. Browser Deepgram `nova-3` dictation if NoMachine microphone transport is unstable.
4. `n-voice` plus Pipecat only for end-to-end conversational agent evaluation.
