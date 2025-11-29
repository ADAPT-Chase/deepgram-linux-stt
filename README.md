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
