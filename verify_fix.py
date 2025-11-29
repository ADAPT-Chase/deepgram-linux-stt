import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add current directory to path so we can import the module
sys.path.append(os.getcwd())

from deepgram_stt_v5 import STTIndicator


class TestSTTFix(unittest.TestCase):
    def test_receive_transcription_handles_1000_error(self):
        # Mock the app
        with patch("tkinter.Tk"), patch("pynput.keyboard.Listener"):
            app = STTIndicator()
            app.is_listening = True

            # Mock the socket
            mock_socket = MagicMock()
            # First call returns None (to skip processing), second raises Exception with "1000"
            mock_socket.recv.side_effect = [
                Exception("WebSocket connection closed: 1000")
            ]

            # Capture stdout
            from io import StringIO

            captured_output = StringIO()
            sys.stdout = captured_output

            # Run the method
            app._receive_transcription(mock_socket)

            # Reset stdout
            sys.stdout = sys.__stdout__

            output = captured_output.getvalue()
            print(f"Captured output: {output}")

            # Verify we see the "normal closure" message and NOT "Error in receive loop"
            self.assertIn("WebSocket closed normally (1000)", output)
            self.assertNotIn("Error in receive loop", output)


if __name__ == "__main__":
    unittest.main()
