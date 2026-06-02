import websockets
import asyncio
import base64
import json
import subprocess
import pyaudio
import os
import numpy as np

OPENHOME_API_KEY = "8ce689a8699cfec6bf9730c3b8dbf493c88d16f24498794e3ad63faf4931e367"
# 0 = default agent; set to a specific personality/agent id (e.g. 238371) to target it.
PERSONALITY_ID = 0
# The server gates the voice-stream on a browser-like User-Agent — a default
# Python/websockets UA is rejected at connect time with 1008 (policy violation).
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

class VoiceStreamer:
    def __init__(self, speaker_type="mpv", personality_id=PERSONALITY_ID):
        self.api_key = OPENHOME_API_KEY
        self.personality_id = personality_id
        # The programmatic path puts the api_key + agent in the URL (the `web/0`
        # path is browser-only — it needs the dashboard session cookies).
        self.server_url = (
            f"wss://app.openhome.com/websocket/voice-stream/{self.api_key}/{self.personality_id}"
        )
        self.frames_per_buffer = 3200
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        self.speaker_type = speaker_type
        self.websocket = None
        self.should_send_audio = True

        # Noise reduction parameters
        self.alpha = 0.95  # Smoothing factor
        self.prev_noise_power = None

        # INITIALIZE PYAUDIO
        self.py_audio_obj = pyaudio.PyAudio()
        self.stream = self._create_stream()
        
        # INITIALIZE PLACEHOLDER FOR MPV
        self.mpv_process = None
        self.speaker = None
        # self.playback_complete = asyncio.Event()
        self.is_speaking = False

    def _create_stream(self):
        """Create the microphone audio stream with better error handling."""
        try:
            # Get default input device info
            device_info = self.py_audio_obj.get_default_input_device_info()
            
            # Adjust parameters based on device capabilities
            supported_rate = min(int(device_info['defaultSampleRate']), self.rate)
            
            stream = self.py_audio_obj.open(
                format=self.format,
                channels=self.channels,
                rate=supported_rate,
                input=True,
                frames_per_buffer=self.frames_per_buffer,
                stream_callback=None,
                start=False  # Don't start immediately
            )
            
            # Test the stream
            stream.start_stream()
            test_data = stream.read(self.frames_per_buffer)
            if not test_data:
                raise IOError("No audio data received")
                
            return stream
            
        except Exception as e:
            print(f"Error creating audio stream: {e}")
            # Try fallback parameters
            return self.py_audio_obj.open(
                format=self.format,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1024
            )

    def process_audio(self, audio_data):
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        audio_float = audio_array.astype(np.float32) / 32768.0
        
        # RMS energy calculation
        rms = np.sqrt(np.mean(audio_float**2))
        
        # Initialize state variables if they don't exist
        if not hasattr(self, 'energy_history'):
            self.energy_history = []
            self.baseline_energy = None
            self.speaking_threshold = 0.03
            self.last_voice_activity = False
            self.voice_holdoff_counter = 0
        
        # Update energy history
        self.energy_history.append(rms)
        if len(self.energy_history) > 30:
            self.energy_history.pop(0)
        
        # Calculate dynamic threshold with different bases for speaking/not speaking
        if self.is_speaking:
            # Much higher threshold when bot is speaking
            dynamic_threshold = np.mean(self.energy_history) * 1.8
        else:
            # Normal threshold when bot is not speaking
            dynamic_threshold = np.mean(self.energy_history) * 1.2
        
        # Significant audio detection with hysteresis
        if not self.last_voice_activity:
            # Higher threshold to start detection
            significant_audio = rms > dynamic_threshold * 1.2
        else:
            # Lower threshold to continue detection
            significant_audio = rms > dynamic_threshold * 0.8
        
        # Voice activity state machine with holdoff
        if significant_audio:
            self.last_voice_activity = True
            self.voice_holdoff_counter = 0
        else:
            self.voice_holdoff_counter += 1
            if self.voice_holdoff_counter > 10:  # Adjust holdoff period as needed
                self.last_voice_activity = False
        
        # If bot is speaking, require much stronger user audio
        if self.is_speaking and rms < dynamic_threshold * 2.0:
            return b'\x00' * len(audio_data)
        
        # If no significant audio, return silence
        if not self.last_voice_activity:
            return b'\x00' * len(audio_data)
        
        # Noise reduction
        if self.prev_noise_power is None:
            self.prev_noise_power = rms**2
            
        noise_power = self.alpha * self.prev_noise_power + (1 - self.alpha) * rms**2
        self.prev_noise_power = noise_power
        
        gain = np.maximum(1 - (noise_power / (rms**2 + 1e-10)), 0.1)
        
        # Additional gain reduction when bot is speaking
        if self.is_speaking:
            gain *= 0.3  # Stronger gain reduction when bot is speaking
        
        processed_audio = audio_float * gain
        
        return (processed_audio * 32768).astype(np.int16).tobytes()

    def pause_mic(self):
        """Pause the microphone stream to prevent capturing speaker's audio."""
        self.should_send_audio = False
        if self.stream.is_active():
            self.stream.stop_stream()
            print("[+] Microphone stream paused")

    def resume_mic(self):
        """Resume the microphone stream after speaker finishes."""
        if not self.stream.is_active():
            self.stream.start_stream()
        self.should_send_audio = True
        print("[+] Microphone stream resumed")

    async def handle_mpv(self):
        """Handle MPV cleanup after audio playback ends."""
        if self.mpv_process and self.mpv_process.stdin:
            try:
                self.mpv_process.stdin.close()
            except BrokenPipeError:
                print("[-] Broken pipe error while writing to MPV")
            await self.mpv_process.communicate()
            self.mpv_process = None

        # self.playback_complete.set()
        self.is_speaking = False
        print("[+] MPV playback completed")

        message = {"type": "text", "data": "bot-speak-end"}
        await self.websocket.send(json.dumps(message))

    async def send_data(self):
        buffer_size = 5  # Number of frames to buffer
        audio_buffer = []
        
        while True:
            try:
                if not self.should_send_audio:
                    await asyncio.sleep(0.01)
                    continue
                    
                audio_bytes = self.stream.read(
                    self.frames_per_buffer, exception_on_overflow=False
                )
                processed_audio = self.process_audio(audio_bytes)
                
                # Buffer the processed audio
                audio_buffer.append(processed_audio)
                if len(audio_buffer) < buffer_size:
                    continue
                    
                # Check if any frame in buffer has significant audio
                has_audio = any(np.frombuffer(frame, dtype=np.int16).any() for frame in audio_buffer)
                
                if has_audio:
                    # Send all buffered frames
                    if self.is_speaking:
                        print("Interrupting")
                        self.mpv_process.stdin.write(b"m\n")
                        message = {"type": "text", "data": "interrupt-event"}
                        await self.websocket.send(json.dumps(message))
                        self.mpv_process.stdin.write(b"q\n")
                        await self.mpv_process.stdin.drain()
                        self.is_speaking = False
                        print("[+] STOPPED MPV...")

                    for frame in audio_buffer:
                        encoded_bytes = base64.b64encode(frame).decode("utf-8")
                        json_data = json.dumps({"type": "audio", "data": encoded_bytes})
                        await self.websocket.send(json_data)
                else:
                    print("NO AUDIO")
                # Clear buffer
                audio_buffer = []
                
            except websockets.exceptions.ConnectionClosedError:
                print("[!] Connection is closed")
                break
            except Exception as e:
                print("[!] Error in send_data:", e)
                self.stream = self._create_stream()
            await asyncio.sleep(0.01)

    async def receive_data(self):
        """Receive data from server and handle it based on speaker type."""
        while True:
            try:
                server_response = await self.websocket.recv()
                data = json.loads(server_response)

                if data["type"] == "text":
                    await self.handle_text_message(data)
                elif data["type"] == "audio":
                    await self.handle_audio_message(data)
                elif data["type"] == "message":
                    await self.handle_chat_message(data["data"])

            except websockets.exceptions.ConnectionClosedError:
                print("[!] Connection is closed")
                break
            except Exception as e:
                print("[!] Error in receive_data:", e)

    async def handle_chat_message(self, data):
        """Process 'chat' type messages from server."""
        if data.get("final",False):
            print("%s: FINAL: %s"%(data.get("role").upper(), data.get("content","")))
        else:
            print("%s: LIVE: %s..."%(data.get("role").upper(), data.get("content","")))

    async def handle_text_message(self, data):
        """Process 'text' type messages from server based on speaker type."""
        if data["data"] == "audio-init":
            print("[+] BOT SPEAKING EVENT IS SET...")
            # self.pause_mic()
            # self.playback_complete.clear()
            self.is_speaking = True

            self.mpv_process = await asyncio.create_subprocess_exec(
                    "mpv", "--no-cache", "--no-terminal", "--", "fd://0",
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            message = {"type": "text", "data": "bot-speaking"}
            await self.websocket.send(json.dumps(message))
            print("[+] SENT BOT SPEAKING EVENT...")

        elif data["data"] == "interrupt":
            print("[+] INTERRUPTION RECEIVED...")
            if self.speaker_type == "mpv" and self.mpv_process and self.mpv_process.stdin:
                self.mpv_process.stdin.write(b"q\n")
                await self.mpv_process.stdin.drain()
                self.is_speaking = False
                print("[+] STOPPED MPV...")

        elif data["data"] == "audio-end":
            print("[+] AUDIO END RECEIVED...")
            if self.speaker_type == "mpv":
                asyncio.get_event_loop().create_task(self.handle_mpv())

            # await self.playback_complete.wait()
            await asyncio.sleep(0.5)
            # self.resume_mic()

    async def handle_audio_message(self, data):
        """Process 'audio' type messages from server."""
        message = {"type": "ack", "data": "audio-received"}
        await self.websocket.send(json.dumps(message))

        audio_bytes = base64.b64decode(data["data"])
        
        if self.speaker_type == "mpv" and self.mpv_process and self.mpv_process.stdin and self.is_speaking:
            self.mpv_process.stdin.write(audio_bytes)
            await self.mpv_process.stdin.drain()

    async def run(self):
        """Establish a connection to the server and start sending/receiving data."""
        try:
            # The browser-like User-Agent is REQUIRED — without it the server
            # closes the connection with 1008 (policy violation).
            async with websockets.connect(
                self.server_url, additional_headers={"User-Agent": BROWSER_UA}
            ) as websocket:
                self.websocket = websocket
                print(f"[+] Connected (personality_id={self.personality_id})")
                await asyncio.gather(self.send_data(), self.receive_data())
        except Exception as e:
            print(e)

    def __del__(self):
        """Cleanup resources."""
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.py_audio_obj:
            self.py_audio_obj.terminate()

if __name__ == "__main__":
    # Default to mpv playback — without a speaker_type, audio frames are never
    # written to the player and you hear nothing.
    voice_streamer = VoiceStreamer(speaker_type=os.getenv("SPEAKER_TYPE") or "mpv")
    asyncio.run(voice_streamer.run())