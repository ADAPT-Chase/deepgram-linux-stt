import os
import sys
import unittest
from unittest.mock import patch


sys.path.append(os.getcwd())

try:
    from remote_faster_whisper_stt import transcript_actions, type_transcript

    IMPORT_ERROR = None
except ImportError as exc:
    transcript_actions = None
    type_transcript = None
    IMPORT_ERROR = exc

try:
    import deepgram_voice_agent_gui as browser_dictation

    BROWSER_IMPORT_ERROR = None
except ImportError as exc:
    browser_dictation = None
    BROWSER_IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"remote STT import unavailable: {IMPORT_ERROR}")
class TestRemoteSttCommands(unittest.TestCase):
    def test_navigation_commands_are_exact(self):
        self.assertEqual(transcript_actions("enter"), [("key", "Return")])
        self.assertEqual(transcript_actions("return"), [("key", "Return")])
        self.assertEqual(transcript_actions("new line"), [("key", "Return")])
        self.assertEqual(transcript_actions("voice enter"), [("key", "Return")])
        self.assertEqual(transcript_actions("wish enter"), [("key", "Return")])
        self.assertEqual(transcript_actions("voice command enter"), [("key", "Return")])
        self.assertEqual(transcript_actions("wish command return"), [("key", "Return")])
        self.assertEqual(transcript_actions("press enter"), [("key", "Return")])
        self.assertEqual(transcript_actions("voice return"), [("key", "Return")])
        self.assertEqual(transcript_actions("wish return"), [("key", "Return")])
        self.assertEqual(transcript_actions("wish next line"), [("key", "Return")])
        self.assertEqual(transcript_actions("wish line break"), [("key", "Return")])
        self.assertEqual(
            transcript_actions("I would like to enter the room"),
            [("text", "I would like to enter the room ")],
        )
        self.assertEqual(
            transcript_actions("I would like to return later"),
            [("text", "I would like to return later ")],
        )

    def test_readback_commands_are_exact(self):
        self.assertEqual(transcript_actions("read back selection"), [("readback",)])
        self.assertEqual(transcript_actions("voice read back selection"), [("readback",)])
        self.assertEqual(transcript_actions("wish command read back selection"), [("readback",)])
        self.assertEqual(transcript_actions("wish read selected text"), [("readback",)])
        self.assertEqual(transcript_actions("read back the selection"), [("readback",)])
        self.assertEqual(transcript_actions("re read back selection"), [("readback",)])
        self.assertEqual(
            transcript_actions("please read back selection when ready"),
            [("text", "please read back selection when ready ")],
        )

    def test_readback_action_does_not_type_text(self):
        with patch("threading.Thread") as thread, patch("subprocess.run") as run:
            type_transcript("wish read back selection")

        self.assertTrue(thread.called)
        self.assertEqual(run.call_count, 0)

    def test_spoken_punctuation_remains_inline(self):
        self.assertEqual(transcript_actions("hello question mark"), [("text", "hello? ")])


@unittest.skipIf(
    BROWSER_IMPORT_ERROR is not None,
    f"browser dictation import unavailable: {BROWSER_IMPORT_ERROR}",
)
class TestBrowserDictationCommands(unittest.TestCase):
    def test_navigation_commands_are_exact(self):
        self.assertEqual(browser_dictation.dictation_actions("voice enter"), [("key", "Return")])
        self.assertEqual(browser_dictation.dictation_actions("wish return"), [("key", "Return")])
        self.assertEqual(
            browser_dictation.dictation_actions("voice command enter"),
            [("key", "Return")],
        )
        self.assertEqual(
            browser_dictation.dictation_actions("wish line break"),
            [("key", "Return")],
        )
        self.assertEqual(
            browser_dictation.dictation_actions("wish next line"),
            [("key", "Return")],
        )
        self.assertEqual(
            browser_dictation.dictation_actions("I would like to return later"),
            [("text", "I would like to return later ")],
        )

    def test_readback_commands_are_exact(self):
        self.assertEqual(
            browser_dictation.dictation_actions("wish read back selection"),
            [("readback", "")],
        )
        self.assertEqual(
            browser_dictation.dictation_actions("re read back selection"),
            [("readback", "")],
        )
        self.assertEqual(
            browser_dictation.dictation_actions("please read back selection when ready"),
            [("text", "please read back selection when ready ")],
        )

    def test_readback_action_does_not_type_text(self):
        with patch("threading.Thread") as thread, patch("subprocess.run") as run:
            browser_dictation.type_dictation_text("wish read back selection")

        self.assertTrue(thread.called)
        self.assertEqual(run.call_count, 0)

    def test_spoken_punctuation_remains_inline(self):
        self.assertEqual(
            browser_dictation.dictation_actions("hello question mark"),
            [("text", "hello? ")],
        )


if __name__ == "__main__":
    unittest.main()
