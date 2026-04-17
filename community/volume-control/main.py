import re
from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


class VolumeControl(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    _os_type = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        # {{register_capability}}
        pass

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    async def detect_os(self):
        """Detect the OS of the LocalLink client machine."""
        if self._os_type:
            return self._os_type
        result = await self.capability_worker.exec_local_command("uname -s")
        uname = result.strip().lower() if result else ""
        if "darwin" in uname:
            self._os_type = "mac"
        elif "linux" in uname:
            self._os_type = "linux"
        else:
            # uname failed — try Windows-style
            result2 = await self.capability_worker.exec_local_command("echo %OS%")
            if result2 and "windows" in result2.strip().lower():
                self._os_type = "windows"
            else:
                self._os_type = "unknown"
        return self._os_type

    async def get_current_volume(self):
        """Get current volume level (0-100) via LocalLink."""
        os_type = await self.detect_os()
        if os_type == "mac":
            cmd = "osascript -e 'output volume of (get volume settings)'"
        elif os_type == "linux":
            cmd = "amixer get Master | grep -oP '\\[\\K[0-9]+(?=%)' | head -1"
        elif os_type == "windows":
            cmd = 'powershell -c "(Get-AudioDevice -PlaybackVolume)"'
        else:
            return 50

        result = await self.capability_worker.exec_local_command(cmd)
        try:
            return int(result.strip())
        except (ValueError, AttributeError):
            return 50

    async def set_volume(self, level):
        """Set volume to a specific level (0-100) via LocalLink."""
        level = min(100, max(0, int(level)))
        os_type = await self.detect_os()

        if os_type == "mac":
            cmd = f"osascript -e 'set volume output volume {level}'"
        elif os_type == "linux":
            cmd = f"amixer set Master {level}%"
        elif os_type == "windows":
            cmd = f'powershell -c "(Set-AudioDevice -PlaybackVolume {level})"'
        else:
            await self.capability_worker.speak("Sorry, volume control isn't supported on this device yet.")
            return level

        await self.capability_worker.exec_local_command(cmd)
        return level

    async def run(self):
        reply = await self.capability_worker.run_io_loop(
            "What would you like? I can raise, lower, set, mute, or max the volume."
        )
        text = reply.strip().lower()

        if any(w in text for w in ["max", "full", "loudest", "all the way up"]):
            await self.set_volume(100)
            await self.capability_worker.speak("Volume set to maximum.")

        elif any(w in text for w in ["mute", "silent", "quiet", "shut up", "zero"]):
            await self.set_volume(0)
            await self.capability_worker.speak("Muted.")

        elif any(w in text for w in ["up", "raise", "higher", "louder", "increase"]):
            current = await self.get_current_volume()
            new_level = await self.set_volume(current + 10)
            await self.capability_worker.speak(f"Volume raised to {new_level} percent.")

        elif any(w in text for w in ["down", "lower", "softer", "quieter", "decrease"]):
            current = await self.get_current_volume()
            new_level = await self.set_volume(current - 10)
            await self.capability_worker.speak(f"Volume lowered to {new_level} percent.")

        else:
            match = re.search(r"(\d+)", text)
            if match:
                level = await self.set_volume(int(match.group(1)))
                await self.capability_worker.speak(f"Volume set to {level} percent.")
            else:
                await self.capability_worker.speak(
                    "I didn't catch that. Try saying raise, lower, mute, max, or a number like 50."
                )

        self.capability_worker.resume_normal_flow()
