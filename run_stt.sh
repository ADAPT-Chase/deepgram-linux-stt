#!/bin/bash
# Run the Deepgram STT application

echo "Starting Deepgram STT Application..."
echo "Make sure you've installed dependencies with: pip install -r requirements.txt"
echo ""
echo "Controls:"
echo "  - Hold ALT key to start listening (indicator turns green)"
echo "  - Release ALT key to stop listening (indicator turns red)"
echo "  - Drag the indicator to move it around your screen"
echo "  - Right-click for more options"
echo ""

python3 deepgram_stt.py
