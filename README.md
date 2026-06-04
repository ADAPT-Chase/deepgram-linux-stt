# Deepgram STT - System-Wide Speech-to-Text

A system-wide speech-to-text application using Deepgram's AI transcription service.

## Features

- **System-wide hotkey**: Press and hold the **ALT** key to activate transcription
- **Visual indicator**: Small, always-on-top indicator that toggles **green** (listening) and **red** (idle)
- **Movable window**: Drag the indicator anywhere on your screen
- **Real-time transcription**: See your speech transcribed live with minimal delay
- **Auto-save**: Transcriptions are automatically saved to `transcriptions.txt`
- **Output window**: View full transcription history with timestamps
- **Dark theme**: Modern dark-themed UI that looks great on any desktop

## Requirements

- Python 3.7 or higher
- A Deepgram API key (sign up at [deepgram.com](https://console.deepgram.com/signup))

## Installation

### 1. Clone or Download

```bash
cd /adapt/projects/stt
```

### 2. Set Up Environment Variables

Your Deepgram API key has already been configured in the `.env` file:

```env
DEEPGRAM_API_KEY=your_api_key_here
```

**Important**: Keep your `.env` file private and never commit API keys to version control!

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

If you encounter issues with `sounddevice`, you may need to install portaudio:

**Ubuntu/Debian:**
```bash
sudo apt-get install portaudio19-dev python3-pyaudio
```

**macOS:**
```bash
brew install portaudio
```

**Windows:**
Install the PyAudio wheel from: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio

### 4. Run the Application

```bash
python deepgram_stt.py
```

## Usage

### Deepgram Voice Agent GUI

The local voice-agent GUI is served by a user systemd service:

```bash
systemctl --user status deepgram-voice-agent-gui.service
```

Open the GUI from the NoMachine desktop:

```text
http://127.0.0.1:18087/
```

The page keeps Deepgram and DeepSeek keys server-side, streams browser
microphone PCM to Deepgram Voice Agent, injects DeepSeek as the server-side
think provider, and plays the returned neural voice audio. The **Mute** button
stops sending microphone frames while the connection remains open.

If the agent shows assistant text but no audible voice, press **Test Sound** in
the GUI. If the test tone is silent, the issue is browser/desktop audio output.
If the test tone works, watch the event log after an agent reply for `audio:
<frames> frames / <bytes> bytes`; a non-zero count means Deepgram returned TTS
audio and the browser received it.

Browser-microphone dictation is available at:

```text
https://dg.adaptdev.ai/dictation
```

This path bypasses NoMachine microphone forwarding. The browser sends 16 kHz
PCM to the server, the server transcribes through Deepgram `nova-3`, and
recognized text is typed into the active X11 text box with `xdotool`.

When `VOICE_AGENT_DICTATION_POLISH=1`, completed dictation segments are routed
through the configured OpenAI-compatible LLM endpoint before typing. This pass is
limited to punctuation, capitalization, paragraph formatting, and obvious STT
duplicate-word cleanup. Spoken key commands are handled locally and skip the LLM
cleanup path. The systemd unit gives the cleanup route a 15-second read timeout
and falls back to the raw transcript if the provider is slow or unavailable.

Spoken dictation commands:
- `enter`, `return`, `new line`, `new paragraph`
- `tab`
- `mute`, `mute on`, `typing off`
- `unmute`, `mute off`, `typing on`
- `question mark`, `exclamation point`, `period`, `comma`, `colon`, `semicolon`, `dash`

### NoMachine Local Dictation

The active local desktop dictation path is `nomachine-remote-stt.service`.
It listens to the NoMachine microphone source `nx_client_mic`, transcribes with
Deepgram `nova-3`, and types into the active X11 field through `xdotool`.

Controls:
- `Ctrl+Space` or `remote-stt-toggle`: toggle dictation on/off.
- `Ctrl+Shift+Space` or `remote-stt-read`: read the selected text aloud.

Muted mode is a hard pause: audio segments are skipped locally and are not sent
to Deepgram. This prevents background audio from creating transcripts while the
operator is paused.

Local NoMachine spoken commands:
- Say `enter`, `return`, `new line`, `next line`, `new paragraph`, or `tab` as a
  standalone segment to send the matching key.
- Optional prefixes `voice` and `wish` are accepted, for example `voice enter`.
- Say `read back selection`, `read selection`, `read selected text`, or
  `read highlighted text` as a standalone segment to read highlighted text aloud.
- Spoken punctuation such as `question mark`, `comma`, and `period` can be used
  inline with dictated text.

### Basic Controls

- **Hold ALT**: Starts listening (indicator turns green)
- **Release ALT**: Stops listening (indicator turns red)
- **Drag window**: Click and drag anywhere on the indicator to move it
- **Right-click**: Shows menu with options to view output or exit

### How It Works

1. When you hold the **ALT** key, the indicator turns **green** and the app starts listening
2. Speak clearly into your microphone
3. Your speech is streamed in real-time to Deepgram's servers
4. Transcription appears in the console and the output window
5. Release **ALT** to stop listening (indicator turns **red**)
6. All transcriptions are automatically saved to `transcriptions.txt`

### Output Window

Right-click the indicator and select "Show Output" to:
- View full transcription history with timestamps
- Clear the output
- Save transcriptions to a separate file

## Configuration

### Customize Settings

Edit the `deepgram_stt.py` file to customize:

**Language:**
```python
language="en-US",  # Change to your preferred language (en-US, es, fr, de, etc.)
```

**Model:**
```python
model="nova-2",  # Use 'nova-2', 'base', or 'enhanced'
```

**Indicator Size and Position:**
```python
self.root.geometry("80x50+100+100")  # width x height + x_position + y_position
```

**Audio Settings:**
```python
sample_rate=16000  # Audio sample rate (default: 16000)
```

## Troubleshooting

### Common Issues

**"DEEPGRAM_API_KEY not found"**
- Make sure `.env` file exists in the same directory
- Verify the API key is correct

**"No microphone detected"**
-   **Typing not working?**: Ensure `xdotool` is installed (`which xdotool`).
-   **Alt key turning off?**: The app has a debounce timer. Wait 0.5s between toggles.
-   **Chrome Remote Desktop**: Typing might be inconsistent in remote sessions due to `xdotool` limitations.

## License

[MIT](LICENSE)

Check the console for:
- Connection status
- Audio device info
- Transcription results
- Error messages

## Deepgram Pricing

Deepgram offers a free tier with limited usage. Check their pricing page for details:
https://deepgram.com/pricing

## Security Notes

- Your API key is stored in `.env` - **never commit this file to git**
- Keep your API key private
- Consider using environment variables in production
- The app saves transcriptions locally - ensure appropriate file permissions

## License

This is a demonstration application. Please refer to Deepgram's terms of service for API usage.

## Support

- Deepgram Documentation: https://developers.deepgram.com/docs
- Deepgram Discord: https://discord.gg/deepgram
- Issues: Create an issue in the project repository

## Changelog

- **v1.0** - Initial release with real-time transcription, ALT key toggle, visual indicator
