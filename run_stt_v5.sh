#!/bin/bash
# Run the Deepgram STT application (SDK v5 compatible)

echo "Starting Deepgram STT Application (SDK v5)..."
echo "Make sure you've installed dependencies with: pip install -r requirements.txt"
echo ""
echo "Controls:"
echo "  - Hold ALT key to start listening (indicator turns green)"
echo "  - Release ALT key to stop listening (indicator turns red)"
echo "  - Drag the indicator to move it around your screen"
echo "  - Right-click for more options"
echo ""

python3 deepgram_stt_v5.py
