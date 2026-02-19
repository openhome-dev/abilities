import json
import os
import platform
import shutil

import psutil
from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# SYSTEM MONITOR
# Voice-driven system health checks. CPU, memory, disk, battery, network,
# and top processes — all spoken back in plain english.
# No API keys, no cloud, no external services. Just your machine.
# =============================================================================

EXIT_WORDS = {
    "stop", "exit", "quit", "done", "bye", "goodbye",
    "leave", "cancel", "no thanks", "i'm good", "im good",
}

MAX_TURNS = 12

SUMMARY_PROMPT = (
    "You are a concise system status reporter speaking to the user. "
    "Summarize this system data in 2-3 short spoken sentences. "
    "Be conversational and highlight anything concerning (high CPU, "
    "low disk space, low battery). If everything looks fine, say so. "
    "Do NOT use bullet points or labels.\n\n"
    "Data:\n{data}"
)

DETAIL_PROMPT = (
    "You are a concise system status reporter. The user asked about: {topic}. "
    "Here is the raw data:\n{data}\n\n"
    "Give a 1-2 sentence spoken summary. Be conversational. "
    "Mention specific numbers but keep it natural."
)


def get_cpu_info():
    """Gather CPU usage and load averages."""
    cpu_percent = psutil.cpu_percent(interval=1)
    cpu_count = psutil.cpu_count()
    load_1, load_5, load_15 = os.getloadavg()
    return {
        "usage_percent": cpu_percent,
        "cores": cpu_count,
        "load_1min": round(load_1, 2),
        "load_5min": round(load_5, 2),
        "load_15min": round(load_15, 2),
    }


def get_memory_info():
    """Gather RAM usage."""
    mem = psutil.virtual_memory()
    return {
        "total_gb": round(mem.total / (1024 ** 3), 1),
        "used_gb": round(mem.used / (1024 ** 3), 1),
        "available_gb": round(mem.available / (1024 ** 3), 1),
        "percent_used": mem.percent,
    }


def get_disk_info():
    """Gather disk usage for the root partition."""
    total, used, free = shutil.disk_usage("/")
    percent = round((used / total) * 100, 1)
    return {
        "total_gb": round(total / (1024 ** 3), 1),
        "used_gb": round(used / (1024 ** 3), 1),
        "free_gb": round(free / (1024 ** 3), 1),
        "percent_used": percent,
    }


def get_battery_info():
    """Gather battery status if available."""
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return None
        return {
            "percent": round(battery.percent),
            "plugged_in": battery.power_plugged,
            "time_left_minutes": (
                round(battery.secsleft / 60)
                if battery.secsleft > 0 else None
            ),
        }
    except (AttributeError, Exception):
        return None


def get_network_info():
    """Gather network interface stats."""
    counters = psutil.net_io_counters()
    return {
        "bytes_sent_mb": round(counters.bytes_sent / (1024 ** 2), 1),
        "bytes_recv_mb": round(counters.bytes_recv / (1024 ** 2), 1),
    }


def get_top_processes(n=5):
    """Get top N processes by CPU usage."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = p.info
            if info["cpu_percent"] is not None:
                procs.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
    top = procs[:n]
    return [
        {
            "name": p.get("name", "unknown"),
            "cpu_percent": round(p.get("cpu_percent", 0), 1),
            "memory_percent": round(p.get("memory_percent", 0), 1),
        }
        for p in top
    ]


def get_uptime():
    """Get system uptime in human-readable form."""
    import time
    boot = psutil.boot_time()
    elapsed = int(time.time() - boot)
    days, remainder = divmod(elapsed, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    return " and ".join(parts) if parts else "just started"


def get_full_snapshot():
    """Collect all system metrics into one dict."""
    snapshot = {
        "platform": platform.platform(),
        "uptime": get_uptime(),
        "cpu": get_cpu_info(),
        "memory": get_memory_info(),
        "disk": get_disk_info(),
        "network": get_network_info(),
        "top_processes": get_top_processes(5),
    }
    battery = get_battery_info()
    if battery:
        snapshot["battery"] = battery
    return snapshot


class SystemMonitorCapability(MatchingCapability):
    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None

    @classmethod
    def register_capability(cls) -> "MatchingCapability":
        with open(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        ) as file:
            data = json.load(file)
        return cls(
            unique_name=data["unique_name"],
            matching_hotwords=data["matching_hotwords"],
        )

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.last_snapshot = None
        self.worker.session_tasks.create(self.run())

    def _log(self, level, msg):
        try:
            handler = self.worker.editor_logging_handler
            getattr(handler, level, handler.info)(f"[SystemMonitor] {msg}")
        except Exception:
            pass

    def detect_command(self, text):
        lower = text.lower().strip()

        if any(w in lower for w in EXIT_WORDS):
            return "exit"
        if any(w in lower for w in ("cpu", "processor", "load")):
            return "cpu"
        if any(w in lower for w in ("memory", "ram", "mem")):
            return "memory"
        if any(w in lower for w in ("disk", "storage", "space", "drive")):
            return "disk"
        if any(w in lower for w in ("battery", "charge", "power")):
            return "battery"
        if any(w in lower for w in ("network", "internet", "bandwidth", "traffic")):
            return "network"
        if any(w in lower for w in ("process", "top", "running", "what's using")):
            return "processes"
        if any(w in lower for w in ("uptime", "how long", "reboot", "restart")):
            return "uptime"
        if any(w in lower for w in (
            "everything", "full", "all", "overview", "summary",
            "again", "refresh", "update", "check again",
        )):
            return "full"

        return "unknown"

    async def speak_summary(self, snapshot):
        """Use LLM to summarize the full snapshot conversationally."""
        try:
            summary = self.capability_worker.text_to_text_response(
                SUMMARY_PROMPT.format(data=json.dumps(snapshot, indent=2))
            )
            await self.capability_worker.speak(summary)
        except Exception as e:
            self._log("error", f"Summary LLM error: {e}")
            # Fallback: speak raw highlights
            cpu = snapshot["cpu"]["usage_percent"]
            mem = snapshot["memory"]["percent_used"]
            disk = snapshot["disk"]["percent_used"]
            await self.capability_worker.speak(
                f"CPU is at {cpu} percent, memory at {mem} percent, "
                f"and disk at {disk} percent used."
            )

    async def speak_detail(self, topic, data):
        """Use LLM to explain a specific metric."""
        try:
            detail = self.capability_worker.text_to_text_response(
                DETAIL_PROMPT.format(topic=topic, data=json.dumps(data, indent=2))
            )
            await self.capability_worker.speak(detail)
        except Exception as e:
            self._log("error", f"Detail LLM error: {e}")
            await self.capability_worker.speak(
                f"Here's the raw data: {json.dumps(data)}"
            )

    async def run(self):
        try:
            await self.capability_worker.speak(
                "Checking your system now."
            )

            self.last_snapshot = get_full_snapshot()
            await self.speak_summary(self.last_snapshot)

            for _ in range(MAX_TURNS):
                user_input = await self.capability_worker.run_io_loop(
                    "Want details on CPU, memory, disk, battery, network, "
                    "or processes? Say done to exit."
                )

                if not user_input or not user_input.strip():
                    continue

                command = self.detect_command(user_input)

                if command == "exit":
                    await self.capability_worker.speak("Got it. Have a good one.")
                    break

                elif command == "full":
                    self.last_snapshot = get_full_snapshot()
                    await self.speak_summary(self.last_snapshot)

                elif command == "cpu":
                    data = get_cpu_info()
                    await self.speak_detail("CPU usage", data)

                elif command == "memory":
                    data = get_memory_info()
                    await self.speak_detail("memory usage", data)

                elif command == "disk":
                    data = get_disk_info()
                    await self.speak_detail("disk space", data)

                elif command == "battery":
                    data = get_battery_info()
                    if data:
                        await self.speak_detail("battery status", data)
                    else:
                        await self.capability_worker.speak(
                            "No battery detected on this system."
                        )

                elif command == "network":
                    data = get_network_info()
                    await self.speak_detail("network traffic", data)

                elif command == "processes":
                    data = get_top_processes(5)
                    await self.speak_detail("top processes by CPU usage", data)

                elif command == "uptime":
                    uptime = get_uptime()
                    await self.capability_worker.speak(
                        f"Your system has been running for {uptime}."
                    )

                else:
                    await self.capability_worker.speak(
                        "You can ask about CPU, memory, disk, battery, "
                        "network, processes, or uptime. Or say done."
                    )

        except Exception as e:
            self._log("error", f"System monitor error: {e}")
            try:
                await self.capability_worker.speak(
                    "Something went wrong checking your system. Try again later."
                )
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()
