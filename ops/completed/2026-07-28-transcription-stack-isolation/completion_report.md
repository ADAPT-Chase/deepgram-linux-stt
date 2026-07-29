# Completion Report

## 2026-07-28 17:15:00 — Codex

The workstation's overlapping transcription and voice stacks were isolated successfully.

- Vocalinux autostart is disabled.
- Deepgram GUI/proxy, Pipecat, `n-voice`, and all associated triggers are disabled and stopped.
- No unrelated NATS or Nova fleet substrate was stopped.
- A zero-listener baseline was verified before testing.
- Only the first candidate, NoMachine Deepgram `nova-3` dictation, was started manually.
- The first candidate remains disabled at boot and can be stopped without altering its config.

Recommended comparison order:

1. NoMachine Deepgram `nova-3` direct dictation.
2. Vocalinux using the installed `small.en-q5_1` model for a fair quality test.
3. Browser Deepgram `nova-3` dictation if NoMachine microphone transport is unstable.
4. `n-voice` plus Pipecat only for end-to-end conversational agent evaluation.
