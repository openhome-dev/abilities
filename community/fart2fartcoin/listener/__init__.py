"""Fart Finder listener: always-on flatulence detector for the OpenHome DevKit.

Runs unsandboxed on the device (Raspberry Pi in production, a Mac during
development). Owns the microphone, runs the three-stage detector, writes
events.jsonl, and serves a Unix socket that devkit_functions.py talks to.
"""
SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
