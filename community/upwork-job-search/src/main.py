# Mock SDK - Main module
from typing import Any

class AgentWorker:
    """Mock AgentWorker class for local development"""
    session_tasks: 'SessionTasks' = None
    editor_logging_handler: 'LoggingHandler' = None

    def __init__(self):
        self.session_tasks = SessionTasks()
        self.editor_logging_handler = LoggingHandler()

class SessionTasks:
    """Mock SessionTasks class"""
    def create(self, coroutine):
        """Create a task from coroutine"""
        import asyncio
        asyncio.create_task(coroutine)
    
    def sleep(self, seconds: float):
        """Async sleep"""
        import asyncio
        return asyncio.sleep(seconds)

class LoggingHandler:
    """Mock LoggingHandler class"""
    def error(self, msg: str):
        print(f"ERROR: {msg}")
    
    def info(self, msg: str):
        print(f"INFO: {msg}")
    
    def warning(self, msg: str):
        print(f"WARNING: {msg}")
