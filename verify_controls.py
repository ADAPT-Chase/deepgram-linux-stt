import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

from deepgram_stt_v5 import STTIndicator


class TestVoiceCommands(unittest.TestCase):
    def test_enter_command(self):
        with (
            patch("tkinter.Tk"),
            patch("pynput.keyboard.Listener"),
            patch("subprocess.run") as mock_run,
        ):
            app = STTIndicator()

            # Test "Enter"
            result = app._process_voice_commands("Enter")
            self.assertTrue(result)
            mock_run.assert_called_with(["xdotool", "key", "Return"], check=True)

            # Test "Enter."
            mock_run.reset_mock()
            result = app._process_voice_commands("Enter.")
            self.assertTrue(result)
            mock_run.assert_called_with(["xdotool", "key", "Return"], check=True)

            # Test "enter" (lowercase)
            mock_run.reset_mock()
            result = app._process_voice_commands("enter")
            self.assertTrue(result)
            mock_run.assert_called_with(["xdotool", "key", "Return"], check=True)

            # Test "Enter something else" (should fail)
            mock_run.reset_mock()
            result = app._process_voice_commands("Enter something else")
            self.assertFalse(result)
            mock_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
