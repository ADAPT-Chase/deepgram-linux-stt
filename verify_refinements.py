import unittest
from unittest.mock import MagicMock, patch, call
import sys
import os
from pynput import keyboard

# Add current directory to path
sys.path.append(os.getcwd())

from deepgram_stt_v5 import STTIndicator


class TestRefinedVoiceCommands(unittest.TestCase):
    def test_explicit_commands(self):
        with (
            patch("tkinter.Tk"),
            patch("pynput.keyboard.Listener"),
            patch("subprocess.run") as mock_run,
        ):
            app = STTIndicator()
            app._add_transcription = MagicMock()
            # Reset mock to ignore calls made during init (like checking xdotool)
            mock_run.reset_mock()

            commands = ["Type Enter", "Press Enter", "New Line", "Next Line"]
            for cmd in commands:
                mock_run.reset_mock()
                app._add_transcription.reset_mock()
                app._process_transcript(cmd)

                # Should NOT type text
                app._add_transcription.assert_not_called()
                # Should execute command
                mock_run.assert_called_with(["xdotool", "key", "Return"], check=True)

    def test_repeated_enter(self):
        with (
            patch("tkinter.Tk"),
            patch("pynput.keyboard.Listener"),
            patch("subprocess.run") as mock_run,
        ):
            app = STTIndicator()
            app._add_transcription = MagicMock()
            mock_run.reset_mock()

            # Test "Enter. Enter."
            app._process_transcript("Enter. Enter.")
            app._add_transcription.assert_not_called()
            self.assertEqual(mock_run.call_count, 2)
            mock_run.assert_has_calls(
                [call(["xdotool", "key", "Return"], check=True)] * 2
            )

            # Test "Enter enter enter"
            mock_run.reset_mock()
            app._process_transcript("Enter enter enter")
            app._add_transcription.assert_not_called()
            self.assertEqual(mock_run.call_count, 3)

    def test_mixed_content_repro(self):
        with (
            patch("tkinter.Tk"),
            patch("pynput.keyboard.Listener"),
            patch("subprocess.run") as mock_run,
        ):
            app = STTIndicator()
            app._add_transcription = MagicMock()
            mock_run.reset_mock()

            # User input: "Test. Test. Test one two. Test. Test one two. Enter. Enter. Enter. Enter. Enter. Enter. Enter. Enter. Still not hitting anything."
            transcript = "Test. Test. Test one two. Test. Test one two. Enter. Enter. Enter. Enter. Enter. Enter. Enter. Enter. Still not hitting anything."

            app._process_transcript(transcript)

            # Should schedule typing of the text part
            # With split logic:
            # "Test. Test. Test one two. Test. Test one two." -> Typed
            # "Enter." x8 -> Executed
            # " Still not hitting anything." -> Typed

            # Verify calls to _add_transcription
            # Note: The exact buffering might result in multiple calls or combined calls depending on logic.
            # Our logic flushes buffer before command.

            # 1. "Test... one two."
            app.root.after.assert_any_call(
                0,
                app._add_transcription,
                "Test. Test. Test one two. Test. Test one two.",
            )

            # 2. " Still not hitting anything."
            app.root.after.assert_any_call(
                0, app._add_transcription, " Still not hitting anything."
            )

            # Should execute 8 Enters
            self.assertEqual(mock_run.call_count, 8)

    def test_mixed_content_simple(self):
        with (
            patch("tkinter.Tk"),
            patch("pynput.keyboard.Listener"),
            patch("subprocess.run") as mock_run,
        ):
            app = STTIndicator()
            app._add_transcription = MagicMock()
            mock_run.reset_mock()

            app._process_transcript("Test. Enter.")

            app.root.after.assert_called_with(0, app._add_transcription, "Test.")
            mock_run.assert_called_once_with(["xdotool", "key", "Return"], check=True)

    def test_alt_key_toggle(self):
        """Test that Alt key toggles listening"""
        with (
            patch("tkinter.Tk"),
            patch("pynput.keyboard.Listener"),
            patch("subprocess.run") as mock_run,
        ):
            app = STTIndicator()
            app.is_listening = False
            app._start_listening = MagicMock()
            app._stop_listening = MagicMock()

            # 1. Press Alt -> Start Listening
            app._on_key_press(keyboard.Key.alt)
            app.root.after.assert_called_with(100, app._start_listening)

            # 2. Release Alt -> Should NOT stop listening (Toggle mode)
            app._on_key_release(keyboard.Key.alt)
            app._stop_listening.assert_not_called()

            # Simulate listening started
            app.is_listening = True

            # 3. Press Alt again -> Stop Listening
            app._on_key_press(keyboard.Key.alt)
            # Use ANY because the bound method instance might differ
            from unittest.mock import ANY

            app.root.after.assert_called_with(100, ANY)

    def test_alt_key_interference_ignored(self):
        """Test that typing flag prevents Alt key press/release from interfering"""
        with (
            patch("tkinter.Tk"),
            patch("pynput.keyboard.Listener"),
            patch("subprocess.run") as mock_run,
        ):
            app = STTIndicator()
            app.is_listening = True
            app._stop_listening = MagicMock()
            app._toggle_listening = MagicMock()

            # Simulate typing active
            app.is_typing = True

            # Press Alt -> Should be ignored
            app._on_key_press(keyboard.Key.alt)
            app._toggle_listening.assert_not_called()

            # Release Alt -> Should be ignored (no state change)
            app._on_key_release(keyboard.Key.alt)
            app._stop_listening.assert_not_called()

    def test_enters_command(self):
        """Test the new 'enters' command"""
        with (
            patch("tkinter.Tk"),
            patch("pynput.keyboard.Listener"),
            patch("subprocess.run") as mock_run,
        ):
            app = STTIndicator()
            app._add_transcription = MagicMock()
            mock_run.reset_mock()

            # "Enters"
            app._process_transcript("Enters")
            mock_run.assert_called_with(["xdotool", "key", "Return"], check=True)

            mock_run.reset_mock()
            # "Enter key"
            app._process_transcript("Enter key")
            mock_run.assert_called_with(["xdotool", "key", "Return"], check=True)


if __name__ == "__main__":
    unittest.main()
