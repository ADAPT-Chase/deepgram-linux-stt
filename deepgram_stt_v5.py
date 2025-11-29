#!/usr/bin/env python3
"""
System-wide Speech-to-Text Application using Deepgram SDK v5
Toggle with ALT key - Green indicates listening, Red indicates idle
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
import queue
import json
import re
import os
import sys
import subprocess
import sounddevice as sd
import numpy as np
from datetime import datetime
from pynput import keyboard
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

# Check for Deepgram API key
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
if not DEEPGRAM_API_KEY:
    print("Error: DEEPGRAM_API_KEY not found in environment variables.")
    print("Please create a .env file with your Deepgram API key.")
    sys.exit(1)

# Import Deepgram SDK
try:
    from deepgram import DeepgramClient

    print("Deepgram SDK imported successfully")
except ImportError as e:
    print(f"Error: Deepgram SDK not installed: {e}")
    print("Please run: pip install -r requirements.txt")
    sys.exit(1)


class STTIndicator:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("STT")
        self.root.geometry("160x100+100+100")

        # Make window always on top
        self.root.attributes("-topmost", True)

        # Remove window decorations (borderless)
        self.root.overrideredirect(True)

        # Make window semi-transparent
        self.root.attributes("-alpha", 0.9)

        # Set background color
        self.root.configure(bg="#2b2b2b")

        # CRITICAL: Set transient property to help with focus behavior
        # This makes the window "always on top" without interfering with typing
        self.root.transient()
        self.root.attributes("-type", "dialog")  # Window type hint

        # Make window movable
        self._drag_data = {"x": 0, "y": 0}
        self.root.bind("<ButtonPress-1>", self._on_drag_start)
        self.root.bind("<ButtonRelease-1>", self._on_drag_stop)
        self.root.bind("<B1-Motion>", self._on_drag_motion)

        # Status indicator frame
        self.status_frame = tk.Frame(self.root, width=120, height=80, bg="#2b2b2b")
        self.status_frame.pack(padx=20, pady=10)

        # Status indicator circle (2x bigger: 60px)
        self.status_circle = tk.Canvas(
            self.status_frame, width=60, height=60, highlightthickness=0, bg="#2b2b2b"
        )
        self.status_circle.pack()

        # Create red circle (default state) - 2x bigger: 56px
        self.indicator = self.status_circle.create_oval(2, 2, 58, 58, fill="#ff4444")

        # Status label (2x bigger font)
        self.status_label = tk.Label(
            self.status_frame,
            text="Idle",
            font=("Arial", 16, "bold"),
            bg="#2b2b2b",
            fg="white",
        )
        self.status_label.pack()

        # State variables
        self.is_listening = False
        self.is_recording = False
        self.is_typing = False  # Flag to prevent Alt key interference
        self.alt_held = False  # Flag to prevent auto-repeat toggling
        self.last_toggle_time = 0  # Debounce timer
        self.deepgram_client = None
        self.audio_queue = queue.Queue()
        self.running = True

        # Output window
        self.output_window = None
        self.text_area = None

        # Typing method: use xdotool (most reliable for X11)
        self.xdotool_available = self._check_xdotool()

        # Bind right-click to toggle listening (no menu)
        self.root.bind("<Button-3>", self._toggle_listening_click)
        self.root.bind("<ButtonRelease-3>", self._unfocus_after_click)

        # Set close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Initialize Deepgram client
        self._init_deepgram()

        # Start audio processing thread
        self._start_audio_thread()

    def _toggle_listening_click(self, event):
        """Toggle listening on right-click"""
        self._toggle_listening()

    def _unfocus_after_click(self, event):
        """Unfocus indicator window after click - simplified approach"""
        # Simply lower and raise to try to remove focus
        try:
            self.root.lower()
            self.root.lift()
        except:
            pass  # Ignore errors

    def _check_xdotool(self):
        """Check if xdotool is available"""
        try:
            result = subprocess.run(
                ["which", "xdotool"], capture_output=True, text=True
            )
            available = result.returncode == 0
            if available:
                print("DEBUG: xdotool found - will use for typing", flush=True)
            else:
                print("DEBUG: xdotool NOT found - typing will not work", flush=True)
            return available
        except Exception as e:
            print(f"DEBUG: Error checking xdotool: {e}", flush=True)
            return False

    def _run_xdotool(self, args):
        """Run xdotool command with typing flag to prevent Alt key interference"""
        self.is_typing = True
        try:
            subprocess.run(args, check=True)
        finally:
            # Increased delay to ensure ALL key release events are processed
            # xdotool might trigger events slightly after it returns
            time.sleep(0.2)
            self.is_typing = False

    def _type_with_xdotool(self, text):
        """Type text using xdotool (most reliable for X11)"""
        try:
            # Use xdotool to type the text
            # We need to escape special characters for shell
            safe_text = text.replace("'", "'\"'\"'")  # Escape single quotes
            safe_text = safe_text.replace("\\", "\\\\")  # Escape backslashes

            cmd = ["xdotool", "type", "--clearmodifiers", "--delay", "10", text]

            # Use internal helper to manage typing flag
            self._run_xdotool(cmd)
            return True

        except Exception as e:
            print(f"DEBUG: Error with xdotool: {e}", flush=True)
            return False

    def _process_transcript(self, transcript):
        """Process transcript, handling commands mixed with text"""
        print(f"DEBUG: Processing transcript: '{transcript}'", flush=True)

        # Split by punctuation to handle sentences/segments
        # Keep delimiters
        parts = re.split(r"([.?!,;]+)", transcript)

        text_buffer = ""
        skip_next_sep = False

        command_map = {
            "enter": "Return",
            "enters": "Return",
            "enter key": "Return",
            "type enter": "Return",
            "press enter": "Return",
            "new line": "Return",
            "next line": "Return",
        }

        for i, part in enumerate(parts):
            # If this is a separator
            if i % 2 == 1:
                if skip_next_sep:
                    skip_next_sep = False
                    continue
                text_buffer += part
                continue

            # This is a content part
            clean_part = part.strip().lower()
            if not clean_part:
                continue

            # Check for explicit commands
            if clean_part in command_map:
                # Flush buffer if any
                if text_buffer:
                    print(f"DEBUG: Flushing buffer: '{text_buffer}'", flush=True)
                    self.root.after(0, self._add_transcription, text_buffer)
                    text_buffer = ""
                    # Wait a bit for typing to finish
                    time.sleep(0.1)

                # Execute command
                key = command_map[clean_part]
                print(f"DEBUG: Executing command: {key}", flush=True)
                try:
                    self._run_xdotool(["xdotool", "key", key])
                except Exception as e:
                    print(f"DEBUG: Error executing command {key}: {e}", flush=True)

                # Skip the next separator (punctuation)
                skip_next_sep = True
                continue

            # Check for repeated "enter" (e.g. "enter enter")
            words = clean_part.split()
            if words and all(w in ["enter", "enters"] for w in words):
                count = len(words)
                # Flush buffer
                if text_buffer:
                    print(f"DEBUG: Flushing buffer: '{text_buffer}'", flush=True)
                    self.root.after(0, self._add_transcription, text_buffer)
                    text_buffer = ""
                    time.sleep(0.1)

                print(f"DEBUG: Executing Enter x{count}", flush=True)
                try:
                    for _ in range(count):
                        self._run_xdotool(["xdotool", "key", "Return"])
                        time.sleep(0.05)
                except Exception as e:
                    print(f"DEBUG: Error executing Enter x{count}: {e}", flush=True)

                skip_next_sep = True
                continue

            # Not a command, add to buffer
            text_buffer += part

        # Flush remaining buffer
        if text_buffer:
            print(f"DEBUG: Flushing remaining buffer: '{text_buffer}'", flush=True)
            self.root.after(0, self._add_transcription, text_buffer)

    def _toggle_output_window(self):
        """Toggle output window"""
        if self.output_window and self.output_window.winfo_exists():
            self.output_window.destroy()
            self.output_window = None
        else:
            self._create_output_window()

    def _create_output_window(self):
        """Create transcription output window"""
        self.output_window = tk.Toplevel(self.root)
        self.output_window.title("Transcription Output")
        self.output_window.geometry("700x500")
        self.output_window.configure(bg="#1e1e1e")

        # Text area for transcriptions
        self.text_area = scrolledtext.ScrolledText(
            self.output_window,
            wrap=tk.WORD,
            font=("Consolas", 11),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
        )
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Button frame
        btn_frame = tk.Frame(self.output_window, bg="#1e1e1e")
        btn_frame.pack(pady=5)

        # Clear button
        clear_btn = tk.Button(
            btn_frame,
            text="Clear",
            command=self._clear_output,
            bg="#0e639c",
            fg="white",
            font=("Arial", 10, "bold"),
        )
        clear_btn.pack(side=tk.LEFT, padx=5)

        # Save button
        save_btn = tk.Button(
            btn_frame,
            text="Save to File",
            command=self._save_output,
            bg="#0e639c",
            fg="white",
            font=("Arial", 10, "bold"),
        )
        save_btn.pack(side=tk.LEFT, padx=5)

    def _clear_output(self):
        """Clear transcription output"""
        if self.text_area:
            self.text_area.delete(1.0, tk.END)

    def _save_output(self):
        """Save transcription output to file"""
        if not self.text_area:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"transcription_{timestamp}.txt"

        content = self.text_area.get(1.0, tk.END)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)

        self._add_transcription(f"\n[Transcription saved to {filename}]")

    def _on_drag_start(self, event):
        """Start dragging window"""
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag_stop(self, event):
        """Stop dragging window"""
        self._drag_data["x"] = 0
        self._drag_data["y"] = 0

    def _on_drag_motion(self, event):
        """Handle window dragging"""
        delta_x = event.x - self._drag_data["x"]
        delta_y = event.y - self._drag_data["y"]
        x = self.root.winfo_x() + delta_x
        y = self.root.winfo_y() + delta_y
        self.root.geometry(f"+{x}+{y}")

    def _init_deepgram(self):
        """Initialize Deepgram client"""
        try:
            self.deepgram_client = DeepgramClient(api_key=DEEPGRAM_API_KEY)
            print("Deepgram client initialized successfully", flush=True)
        except Exception as e:
            print(f"Error initializing Deepgram client: {e}", flush=True)
            sys.exit(1)

    def _start_audio_thread(self):
        """Start background audio processing thread"""
        self.audio_thread = threading.Thread(target=self._audio_worker, daemon=True)
        self.audio_thread.start()

    def _audio_worker(self):
        """Process audio from queue"""
        while self.running:
            time.sleep(0.1)

    def _toggle_listening(self):
        """Toggle listening state"""
        if not self.is_listening:
            self._start_listening()
        else:
            self._stop_listening()

    def _force_focus_to_active_window(self):
        """Force keyboard focus to whatever window is active (not our indicator)"""
        try:
            # Simulate an Alt+Tab to switch focus away from our window
            # but quickly so it doesn't actually switch applications
            self.keyboard_controller.press(keyboard.Key.alt)
            time.sleep(0.01)
            self.keyboard_controller.release(keyboard.Key.alt)
            time.sleep(0.05)  # Brief pause to let focus settle
            print("DEBUG: Forced focus to active window", flush=True)
        except Exception as e:
            print(f"DEBUG: Could not force focus: {e}", flush=True)

    def _on_transcript_event(self, event):
        """Handle incoming transcription event object (already parsed)"""
        try:
            print(f"DEBUG: Received event from Deepgram: {type(event).__name__}")

            # Check if it's a results event
            if hasattr(event, "type") and event.type == "Results":
                # Try different attribute names
                channel = None
                if hasattr(event, "channel"):
                    channel = event.channel
                elif hasattr(event, "results") and event.results:
                    # Event might have results structure
                    results = event.results
                    if hasattr(results, "channels") and results.channels:
                        channel = results.channels[0]

                if channel:
                    alternatives = getattr(channel, "alternatives", [])
                    if alternatives and len(alternatives) > 0:
                        alt = alternatives[0]
                        transcript = getattr(alt, "transcript", "")
                        if transcript and transcript.strip():
                            print(f"DEBUG: Transcript: {transcript}", flush=True)

                            # Process transcript for mixed content (text + commands)
                            self._process_transcript(transcript)
        except Exception as e:
            print(f"DEBUG: Error in _on_transcript_event: {e}", flush=True)

    def _start_listening(self):
        """Start listening/transcribing"""
        if self.is_listening:
            print("Already listening, ignoring _start_listening call")
            return

        try:
            # Update UI
            self.is_listening = True
            self.status_circle.itemconfig(self.indicator, fill="#44ff44")
            self.status_label.config(text="Listening")

            print("DEBUG: Starting audio recording thread...")
            # Start recording thread
            self.is_recording = True
            self.recording_thread = threading.Thread(
                target=self._record_audio, daemon=True
            )
            self.recording_thread.start()

            print("Started listening...")

        except Exception as e:
            print(f"Error starting transcription: {e}")
            self._stop_listening()

    def _stop_listening(self):
        """Stop listening/transcribing"""
        if not self.is_listening:
            print("Not listening, ignoring _stop_listening call")
            return

        try:
            # Update UI
            self.is_listening = False
            self.status_circle.itemconfig(self.indicator, fill="#ff4444")
            self.status_label.config(text="Idle")

            print("Stopped listening...")

        except Exception as e:
            print(f"Error stopping transcription: {e}")

    def _record_audio(self):
        """Record audio from microphone and transcribe"""
        try:
            device_info = sd.query_devices(kind="input")
            samplerate = int(device_info["default_samplerate"])

            print(f"DEBUG: Recording from: {device_info['name']} at {samplerate}Hz")

            # Use the context manager properly for WebSocket connection
            with self.deepgram_client.listen.v1.connect(
                model="nova-2",
                language="en-US",
                punctuate="true",
                interim_results="true",
                encoding="linear16",
                sample_rate=str(samplerate),
                channels="1",
            ) as socket:
                print("DEBUG: Connected to Deepgram WebSocket")

                # Start receiving transcription results in a separate thread
                receive_thread = threading.Thread(
                    target=self._receive_transcription, args=(socket,), daemon=True
                )
                receive_thread.start()

                def audio_callback(indata, frames, time_info, status):
                    if status:
                        print(f"DEBUG: Audio status: {status}")
                    if self.is_listening:
                        # Send audio to Deepgram using send_media()
                        audio_bytes = indata.tobytes()
                        print(f"DEBUG: Sending {len(audio_bytes)} bytes of audio")
                        socket.send_media(audio_bytes)

                with sd.InputStream(
                    callback=audio_callback,
                    channels=1,
                    samplerate=samplerate,
                    dtype="int16",
                    blocksize=int(samplerate * 0.1),  # 100ms chunks
                ):
                    print("DEBUG: Recording started...")
                    while self.is_listening:
                        time.sleep(0.1)

                print("DEBUG: Recording stopped")

        except Exception as e:
            print(f"DEBUG: Error in audio recording/transcription: {e}", flush=True)
            import traceback

            traceback.print_exc()
            self.root.after(0, self._stop_listening)

    def _receive_transcription(self, socket):
        """Receive transcription results in a separate thread"""
        try:
            print("DEBUG: Starting transcription receive thread")
            while self.is_listening:
                try:
                    # Use recv() not receive() - returns event objects, not JSON
                    result = socket.recv()
                    if result:
                        self._on_transcript_event(result)
                except Exception as e:
                    # Check for normal closure (code 1000)
                    if "1000" in str(e):
                        print("DEBUG: WebSocket closed normally (1000)", flush=True)
                    else:
                        print(f"DEBUG: Error in receive loop: {e}", flush=True)
                    break
                time.sleep(0.01)
        except Exception as e:
            print(f"DEBUG: Exception in receive thread: {e}", flush=True)

    def _on_transcript_event(self, event):
        """Handle incoming transcription event object (already parsed)"""
        try:
            print(f"DEBUG: Received event from Deepgram: {type(event).__name__}")

            # Check if it's a results event
            if hasattr(event, "type") and event.type == "Results":
                # Try different attribute names
                channel = None
                if hasattr(event, "channel"):
                    channel = event.channel
                elif hasattr(event, "results") and event.results:
                    # Event might have results structure
                    results = event.results
                    if hasattr(results, "channels") and results.channels:
                        channel = results.channels[0]

                if channel:
                    alternatives = getattr(channel, "alternatives", [])
                    if alternatives and len(alternatives) > 0:
                        alt = alternatives[0]
                        transcript = getattr(alt, "transcript", "")
                        if transcript and transcript.strip():
                            print(f"DEBUG: Transcript: {transcript}", flush=True)
                            self.root.after(0, self._add_transcription, transcript)
        except Exception as e:
            print(f"DEBUG: Error in _on_transcript_event: {e}", flush=True)

    def _add_transcription(self, text):
        """Add transcription to output window AND type into active window"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_text = f"[{timestamp}] {text}\n"

        print(formatted_text, end="", flush=True)

        # Type into any active window/application
        self._type_into_active_window(text)

        if self.text_area and self.text_area.winfo_exists():
            self.text_area.insert(tk.END, formatted_text)
            self.text_area.see(tk.END)

        # Auto-save to file
        try:
            with open("transcriptions.txt", "a", encoding="utf-8") as f:
                f.write(formatted_text)
        except Exception as e:
            print(f"DEBUG: Error saving to file: {e}", flush=True)

    def _type_into_active_window(self, text):
        """Type transcription into currently active window using xdotool"""
        if not self.xdotool_available:
            print("DEBUG: ERROR - xdotool not available, cannot type!", flush=True)
            print("DEBUG: Install xdotool: sudo apt install xdotool", flush=True)
            return

        try:
            # Add space after text for natural typing
            text_to_type = text + " "

            print(
                f"DEBUG: Typing into active window: '{text_to_type.strip()}'",
                flush=True,
            )

            success = self._type_with_xdotool(text_to_type)

            if success:
                print(f"DEBUG: Successfully typed: {text}", flush=True)
            else:
                print(f"DEBUG: Failed to type: {text}", flush=True)
                print(f"DEBUG: Make sure you clicked into a text box!", flush=True)

        except Exception as e:
            print(f"DEBUG: Error typing into window: {e}", flush=True)
            print(
                f"DEBUG: Make sure you clicked into a text box before transcribing!",
                flush=True,
            )

    def _on_closing(self):
        """Handle window closing"""
        self._stop_listening()
        self.running = False
        self.root.destroy()

    def run(self):
        """Run the application"""
        print("=" * 60, flush=True)
        print("Deepgram STT Speech-to-Text Agent", flush=True)
        print("=" * 60, flush=True)
        print("", flush=True)
        print("✅ READY - Right-click indicator to start listening", flush=True)
        print("🎙️ Speak clearly - transcription will type automatically", flush=True)
        print(
            "📋 CLICK into a text box first, then right-click to transcribe", flush=True
        )
        print("", flush=True)
        print("Requirements:", flush=True)
        print(
            "  • xdotool is available: {}".format(
                "✅ YES" if self.xdotool_available else "❌ NO"
            ),
            flush=True,
        )
        print(
            "  • Deepgram API key: {}".format(
                "✅ SET" if DEEPGRAM_API_KEY else "❌ MISSING"
            ),
            flush=True,
        )
        print("", flush=True)
        if not self.xdotool_available:
            print("⚠️  WARNING: xdotool not found! Typing will not work.", flush=True)
            print("   Install with: sudo apt install xdotool", flush=True)
        print("=" * 60, flush=True)

        # Start keyboard listener
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press, on_release=self._on_key_release
        )
        self.keyboard_listener.start()

        self.root.mainloop()

    def _on_key_press(self, key):
        """Handle key press events"""
        print(f"DEBUG: Key pressed: {key}", flush=True)
        if key == keyboard.Key.alt:
            print("DEBUG: ALT key detected!", flush=True)
            if not self.is_listening:
                print("=== HOLD ALT TO START TRANSCRIBING ===", flush=True)
                # Small delay to ensure focus is on the target window
                self.root.after(100, self._start_listening)
                # Do NOT change transparency - keep it bright
                print(
                    "=== SPEAK NOW - Words will type where your cursor is ===",
                    flush=True,
                )
            else:
                print("ALT key pressed but already listening", flush=True)
        elif hasattr(key, "value") and hasattr(key, "name"):
            # Handle Ctrl+Space (Space when Ctrl is held)
            print(f"DEBUG: Checking for Ctrl+Space: {key}", flush=True)
        else:
            print(f"Other key pressed: {key}", flush=True)

    def _on_key_release(self, key):
        """Handle key release events"""
        print(f"Key released: {key}", flush=True)
        if key == keyboard.Key.alt and self.is_listening:
            # Stop listening when ALT is released (press-and-hold mode)
            print("=== RELEASED ALT - STOPPED LISTENING ===", flush=True)
            self.root.after(100, self._stop_listening)
            print("=== Click into a text box, then HOLD ALT and speak ===", flush=True)


if __name__ == "__main__":
    app = STTIndicator()
    app.run()
