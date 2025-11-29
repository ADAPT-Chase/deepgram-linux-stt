#!/usr/bin/env python3
"""Test keyboard detection"""

from pynput import keyboard
import time

print("Testing keyboard ALT key detection...")
print("Press and release ALT key a few times, then press ESC to exit")

count = 0

def on_press(key):
    global count
    if key == keyboard.Key.alt:
        count += 1
        print(f"ALT pressed! Count: {count}")
    elif key == keyboard.Key.esc:
        print("ESC pressed - exiting")
        return False
    else:
        print(f"Other key pressed: {key}")

def on_release(key):
    if key == keyboard.Key.alt:
        print("ALT released!")

listener = keyboard.Listener(on_press=on_press, on_release=on_release)
listener.start()

listener.wait()
print("\nTest complete!")
