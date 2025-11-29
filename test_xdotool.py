import subprocess
import time
import sys


def test_typing():
    print("Testing xdotool typing...")
    print("Please click into a text editor or terminal window within 3 seconds...")
    for i in range(3, 0, -1):
        print(f"{i}...", flush=True)
        time.sleep(1)

    text = "Hello from xdotool!"
    cmd = ["xdotool", "type", "--clearmodifiers", "--delay", "50", text]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"\nSuccessfully typed: '{text}'")
        else:
            print(f"\nError typing: {result.stderr}")
    except Exception as e:
        print(f"\nException: {e}")


if __name__ == "__main__":
    test_typing()
