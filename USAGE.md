# Deepgram STT - Speech-to-Text Agent

## ✅ APPLICATION IS WORKING!

**The Speech-to-Text application is fully functional and operational!**

## 📍 How to Find the Indicator:

**Position**: Top-left of your screen at coordinates (100, 100)

**What to look for**:
- 🔴 **RED circle** (60px) - App is idle, waiting
- 🟢 **GREEN circle** - App is listening and transcribing
- **"Idle" / "Listening"** text below the circle
- Dark themed, semi-transparent window

## 🎯 How to Use:

### 1. **Start the App:**
```bash
cd /adapt/projects/stt
./run_stt_v5.sh
```

### 2. **Use the App:**
1. **Click into ANY text box** (browser, terminal, editor, etc.)
2. **Right-click the indicator** → Turns 🟢 **GREEN**
3. **Speak clearly** → Your words automatically type into the text box!
4. **Right-click again** → Turns 🔴 **RED** to stop

### 3. **Features:**
- ✅ Real-time transcription via Deepgram API
- ✅ Automatic typing into any active window
- ✅ Visual indicator shows status
- ✅ Draggable - click and drag to move
- ✅ Always-on-top window
- ✅ Auto-saves transcriptions

## 🔧 Technical Details:

**What works:**
- Microphone capture ✅
- Deepgram WebSocket streaming ✅
- xdotool automatic typing ✅
- Visual indicator ✅
- Right-click toggle ✅

**Log files:**
- `stt_debug.log` - Debug output
- `transcriptions.txt` - All transcriptions saved

## 📖 Files:

- `deepgram_stt_v5.py` - Main application
- `run_stt_v5.sh` - Launcher script
- `deepgram-python-sdk/` - Official Deepgram SDK v5
- `requirements.txt` - Python dependencies
- `.env` - API key configuration

## 🎉 Status: **FULLY OPERATIONAL!**

The application is working perfectly. It transcribes speech and automatically types into your active window using xdotool.
