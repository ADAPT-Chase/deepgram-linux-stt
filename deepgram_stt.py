#!/usr/bin/env python3
"""
System-wide Speech-to-Text Application using Deepgram
Toggle with ALT key - Green indicates listening, Red indicates idle
"""

import tkinter as tk
from tkinter import scrolledtext
import threading
import queue
import asyncio
import json
import os
import sys
import sounddevice as sd
import numpy as np
from datetime import datetime
from pynput import keyboard
from dotenv import load_dotenv
import base64
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
    from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions, Microphone
    print("Deepgram SDK imported successfully")
except ImportError:
    print("Error: Deepgram SDK not installed")
    print("Please run: pip install -r requirements.txt")
    sys.exit(1)

class STTIndicator:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("STT")
        self.root.geometry("80x50+100+100")  # Small window, position at (100, 100)

        # Make window always on top
        self.root.attributes('-topmost', True)

        # Remove window decorations (borderless)
        self.root.overrideredirect(True)

        # Make window semi-transparent
        self.root.attributes('-alpha', 0.9)

        # Set background color
        self.root.configure(bg='#2b2b2b')

        # Make window movable
        self._drag_data = {"x": 0, "y": 0}
        self.root.bind("<ButtonPress-1>", self._on_drag_start)
        self.root.bind("<ButtonRelease-1>", self._on_drag_stop)
        self.root.bind("<B1-Motion>", self._on_drag_motion)

        # Status indicator frame
        self.status_frame = tk.Frame(self.root, width=60, height=40, bg='#2b2b2b')
        self.status_frame.pack(padx=10, pady=5)

        # Status indicator circle
        self.status_circle = tk.Canvas(self.status_frame, width=30, height=30,
                                       highlightthickness=0, bg='#2b2b2b')
        self.status_circle.pack()

        # Create red circle (default state)
        self.indicator = self.status_circle.create_oval(2, 2, 28, 28, fill="#ff4444")

        # Status label
        self.status_label = tk.Label(self.status_frame, text="Idle",
                                     font=("Arial", 8, "bold"),
                                     bg='#2b2b2b', fg='white')
        self.status_label.pack()

        # State variables
        self.is_listening = False
        self.is_recording = False
        self.deepgram_client = None
        self.deepgram_connection = None
        self.microphone = None

        # Output window
        self.output_window = None
        self.text_area = None

        # Create menu
        self._create_menu()

        # Set close handler
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Initialize Deepgram client
        self._init_deepgram()

    def _create_menu(self):
        """Create right-click menu"""
        self.menu = tk.Menu(self.root, tearoff=0, bg='#2b2b2b', fg='white')
        self.menu.add_command(label="Show Output", command=self._toggle_output_window)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self._on_closing)

        # Bind right-click
        self.root.bind("<Button-3>", self._show_menu)

    def _show_menu(self, event):
        """Show context menu"""
        self.menu.post(event.x_root, event.y_root)

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
        self.output_window.configure(bg='#1e1e1e')

        # Text area for transcriptions
        self.text_area = scrolledtext.ScrolledText(
            self.output_window,
            wrap=tk.WORD,
            font=("Consolas", 11),
            bg='#1e1e1e',
            fg='#d4d4d4',
            insertbackground='white'
        )
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Button frame
        btn_frame = tk.Frame(self.output_window, bg='#1e1e1e')
        btn_frame.pack(pady=5)

        # Clear button
        clear_btn = tk.Button(
            btn_frame,
            text="Clear",
            command=self._clear_output,
            bg='#0e639c',
            fg='white',
            font=("Arial", 10, "bold")
        )
        clear_btn.pack(side=tk.LEFT, padx=5)

        # Save button
        save_btn = tk.Button(
            btn_frame,
            text="Save to File",
            command=self._save_output,
            bg='#0e639c',
            fg='white',
            font=("Arial", 10, "bold")
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
            self.deepgram_client = DeepgramClient(DEEPGRAM_API_KEY)
            print("Deepgram client initialized successfully")
        except Exception as e:
            print(f"Error initializing Deepgram client: {e}")
            sys.exit(1)

    def _on_transcript(self, self_ref, result, **kwargs):
        """Handle incoming transcript from Deepgram"""
        try:
            data = json.loads(result)
            if data.get("channel"):
                transcript = data["channel"]["alternatives"][0]["transcript"]
                if transcript and transcript.strip():
                    self.root.after(0, self._add_transcription, transcript)
        except Exception as e:
            print(f"Error processing transcript: {e}")

    def _on_error(self, self_ref, error, **kwargs):
        """Handle errors from Deepgram"""
        print(f"Deepgram error: {error}")

    def _toggle_listening(self):
        """Toggle listening state"""
        if not self.is_listening:
            self._start_listening()
        else:
            _stop_listening()

    def _start_listening(self):
        """Start listening/transcribing"""
        try:
            # Update UI
            self.is_listening = True
            self.status_circle.itemconfig(self.indicator, fill="#44ff44")
            self.status_label.config(text="Listening")

            # Create Deepgram connection
            self.deepgram_connection = self.deepgram_client.listen.asynclive.v("1")

            # Register event handlers
            self.deepgram_connection.on(LiveTranscriptionEvents.Transcript, self._on_transcript)
            self.deepgram_connection.on(LiveTranscriptionEvents.Error, self._on_error)

            # Configure options
            options = LiveOptions(
                model="nova-2",
                language="en-US",
                punctuate=True,
                interim_results=True,
                encoding="linear16",
                channels=1,
                sample_rate=16000
            )

            # Start connection
            if self.deepgram_connection.start(options) is False:
                raise Exception("Failed to connect to Deepgram")

            # Start microphone
            self.microphone = Microphone(self.deepgram_connection.send)
            self.microphone.start()

            print("Started listening...")

        except Exception as e:
            print(f"Error starting transcription: {e}")
            self._stop_listening()

    def _stop_listening(self):
        """Stop listening/transcribing"""
        try:
            # Stop microphone
            if self.microphone:
                self.microphone.finish()
                self.microphone = None

            # Close Deepgram connection
            if self.deepgram_connection:
                self.deepgram_connection.finish()
                self.deepgram_connection = None

            # Update UI
            self.is_listening = False
            self.status_circle.itemconfig(self.indicator, fill="#ff4444")
            self.status_label.config(text="Idle")

            print("Stopped listening...")

        except Exception as e:
            print(f"Error stopping transcription: {e}")

    def _add_transcription(self, text):
        """Add transcription to output window"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_text = f"[{timestamp}] {text}\n"

        print(formatted_text, end='')

        if self.text_area and self.text_area.winfo_exists():
            self.text_area.insert(tk.END, formatted_text)
            self.text_area.see(tk.END)

            # Auto-save to file
            with open("transcriptions.txt", "a", encoding="utf-8") as f:
                f.write(formatted_text)

    def _on_closing(self):
        """Handle window closing"""
        self._stop_listening()
        self.running = False
        self.root.destroy()

    def run(self):
        """Run the application"""
        print("Starting STT Application...")
        print("Press and hold ALT key to toggle listening")
        print("Right-click the indicator for options")
        print("Window is draggable")

        # Start keyboard listener
        self.keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release
        )
        self.keyboard_listener.start()

        self.root.mainloop()

    def _on_key_press(self, key):
        """Handle key press events"""
        if key == keyboard.Key.alt:
            if not self.is_listening:
                self.root.after(0, self._start_listening)

    def _on_key_release(self, key):
        """Handle key release events"""
        if key == keyboard.Key.alt:
            if self.is_listening:
                self.root.after(0, self._stop_listening)

if __name__ == "__main__":
    app = STTIndicator()
    app.run()
