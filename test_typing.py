#!/usr/bin/env python3
"""Simple test of keyboard typing functionality"""

from pynput.keyboard import Controller
import time

print("Testing keyboard typing...")
print("Click into a text box now!")
print("Typing in 3 seconds...")

time.sleep(3)

keyboard = Controller()
test_text = "Hello world! This is a typing test. "

print(f"About to type: {test_text}")

for char in test_text:
    keyboard.type(char)
    time.sleep(0.01)

print("Done!")
