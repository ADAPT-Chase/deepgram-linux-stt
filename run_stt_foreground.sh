#!/bin/bash
# Run STT app in FOREGROUND to ensure window appears

echo "Starting Deepgram STT Application..."
echo "Make sure you're in an X11 session with a display"
echo ""
echo "The indicator window should appear at position 100,100"
echo "Look in the TOP-LEFT area of your screen!"
echo ""
echo "If you don't see it after 5 seconds, check:"
echo "  - Are you in a graphical X11 session?"
echo "  - Is your DISPLAY variable set? (echo \$DISPLAY)"
echo ""
echo "Press Ctrl+C to exit"
echo ""
echo "=========================================="

# Run in foreground so the window definitely appears
python3 deepgram_stt_v5.py 2>&1 | tee stt_debug.log
