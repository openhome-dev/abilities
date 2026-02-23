# Mock SDK - CapabilityWorker module
from typing import Optional, Any

class CapabilityWorker:
    """Mock CapabilityWorker class for local development"""
    
    def __init__(self, worker):
        self.worker = worker

    async def speak(self, text: str):
        """Speak text to the user"""
        print(f"AI: {text}")

    async def user_response(self) -> str:
        """Get user's voice response"""
        return input("👤 User: ")

    async def wait_for_complete_transcription(self) -> str:
        """Wait for complete transcription"""
        return input("👤 User: ")

    def resume_normal_flow(self):
        """Resume normal conversation flow"""
        print("Resuming normal flow...")

    async def text_to_text_response(self, prompt: str) -> str:
        """Get text-to-text response from LLM"""
        print(f"LLM Prompt: {prompt}")
        return input("LLM Response: ")

    # File operations (mock)
    async def read_file(self, path: str) -> str:
        """Read a file"""
        with open(path, 'r') as f:
            return f.read()

    async def write_file(self, path: str, content: str):
        """Write to a file"""
        with open(path, 'w') as f:
            f.write(content)

    async def file_exists(self, path: str) -> bool:
        """Check if file exists"""
        import os
        return os.path.exists(path)
