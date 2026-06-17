import json
import shutil
import subprocess
import sys
import time
from devkit_utils.devkit_logging import web_logger as log


def _emit_success(metric, spoken, data=None):
    payload = {
        "success": True,
        "metric": metric,
        "spoken_response": spoken,
        "data": data or {},
        "error": None,
    }
    serialized_payload = json.dumps(payload)
    log.info("stdout payload: %s", serialized_payload)
    print(serialized_payload)


def _emit_error(metric, code, message, spoken):
    log.error("%s failed [%s]: %s", metric, code, message)
    payload = {
        "success": False,
        "metric": metric,
        "spoken_response": spoken,
        "data": {},
        "error": {
            "code": code,
            "message": message,
        },
    }
    serialized_payload = json.dumps(payload)
    log.info("stdout payload: %s", serialized_payload)
    print(serialized_payload)


def _read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as file_handle:
            return file_handle.read().strip()
    except (FileNotFoundError, PermissionError, OSError) as error:
        log.warning("Could not read %s: %s", path, error)
        return ""


def _run_command(command, timeout=5):
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log.warning("Command timed out: %s", command)
        return ""
    except OSError as error:
        log.warning("Command failed: %s: %s", command, error)
        return ""

    if completed.returncode != 0:
        log.warning("Command returned %s: %s", completed.returncode, command)
        return ""

    return completed.stdout.strip()


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_memory_kb(field_name):
    meminfo = _read_text_file("/proc/meminfo")
    for line in meminfo.splitlines():
        if line.startswith(field_name):
            value = line.split(":", 1)[1].strip().split()[0]
            return _safe_int(value)
    return None


def _read_cpu_sample():
    stat = _read_text_file("/proc/stat")
    for line in stat.splitlines():
        if line.startswith("cpu "):
            values = [_safe_int(value) or 0 for value in line.split()[1:]]
            if len(values) < 4:
                return None
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            return {"idle": idle, "total": sum(values)}
    return None


def _read_cpu_usage_percent(sample_seconds=0.4):
    first = _read_cpu_sample()
    time.sleep(sample_seconds)
    second = _read_cpu_sample()

    if not first or not second:
        return None

    total_delta = second["total"] - first["total"]
    idle_delta = second["idle"] - first["idle"]
    if total_delta <= 0:
        return None

    return round((1 - idle_delta / total_delta) * 100)


def _gb_from_kb(value):
    if value is None:
        return None
    return round(value / 1024 / 1024, 1)


def _temperature_status(celsius):
    if celsius < 50:
        return "running cool"
    if celsius < 65:
        return "comfortable"
    if celsius < 75:
        return "warm"
    if celsius < 85:
        return "hot"
    return "very hot"


def get_cpu():
    metric = "cpu"
    log.info("get_cpu called")
    try:
        used_percent = _read_cpu_usage_percent()
        if used_percent is None:
            _emit_error(metric, "cpu_unavailable", "CPU usage could not be read.", "I couldn't read CPU usage.")
            return

        free_percent = 100 - used_percent
        _emit_success(
            metric,
            f"CPU is {used_percent} percent used and {free_percent} percent free.",
            {"used_percent": used_percent, "free_percent": free_percent},
        )
    except Exception as error:
        log.exception("Unhandled error in get_cpu")
        _emit_error(metric, "cpu_error", str(error), "I couldn't read CPU usage.")


def get_memory():
    metric = "memory"
    log.info("get_memory called")
    try:
        total_gb = _gb_from_kb(_read_memory_kb("MemTotal:"))
        available_gb = _gb_from_kb(_read_memory_kb("MemAvailable:"))
        if total_gb is None or available_gb is None:
            _emit_error(metric, "memory_unavailable", "Memory info could not be read.", "I couldn't read memory usage.")
            return

        used_gb = round(total_gb - available_gb, 1)
        _emit_success(
            metric,
            f"Memory has {used_gb} gigabytes used out of {total_gb}, with {available_gb} gigabytes available.",
            {"total_gb": total_gb, "used_gb": used_gb, "available_gb": available_gb},
        )
    except Exception as error:
        log.exception("Unhandled error in get_memory")
        _emit_error(metric, "memory_error", str(error), "I couldn't read memory usage.")


def get_temperature():
    metric = "temperature"
    log.info("get_temperature called")
    try:
        raw_value = _read_text_file("/sys/class/thermal/thermal_zone0/temp")
        millicelsius = _safe_int(raw_value)
        if millicelsius is None:
            _emit_error(metric, "temperature_unavailable", "Temperature value could not be read.", "I couldn't read the DevKit temperature.")
            return

        celsius = round(millicelsius / 1000, 1)
        status = _temperature_status(celsius)
        _emit_success(
            metric,
            f"DevKit temperature is {celsius} degrees Celsius and {status}.",
            {"celsius": celsius, "status": status},
        )
    except Exception as error:
        log.exception("Unhandled error in get_temperature")
        _emit_error(metric, "temperature_error", str(error), "I couldn't read the DevKit temperature.")


def get_uptime():
    metric = "uptime"
    log.info("get_uptime called")
    try:
        uptime_text = _read_text_file("/proc/uptime")
        uptime_seconds = _safe_float(uptime_text.split()[0]) if uptime_text else None
        if uptime_seconds is None:
            _emit_error(metric, "uptime_unavailable", "Uptime could not be read.", "I couldn't read DevKit uptime.")
            return

        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        if days:
            spoken_duration = f"{days} days and {hours} hours"
        elif hours:
            spoken_duration = f"{hours} hours and {minutes} minutes"
        else:
            spoken_duration = f"{minutes} minutes"

        _emit_success(
            metric,
            f"The DevKit has been running for {spoken_duration}.",
            {"seconds": round(uptime_seconds), "days": days, "hours": hours, "minutes": minutes},
        )
    except Exception as error:
        log.exception("Unhandled error in get_uptime")
        _emit_error(metric, "uptime_error", str(error), "I couldn't read DevKit uptime.")


def get_wifi():
    metric = "wifi"
    log.info("get_wifi called")
    try:
        ssid = _run_command("iwgetid -r 2>/dev/null")
        if not ssid:
            _emit_success(metric, "Wi-Fi is not connected.", {"connected": False, "ssid": None})
            return

        _emit_success(metric, f"Wi-Fi is connected to {ssid}.", {"connected": True, "ssid": ssid})
    except Exception as error:
        log.exception("Unhandled error in get_wifi")
        _emit_error(metric, "wifi_error", str(error), "I couldn't read Wi-Fi status.")


def get_disk():
    metric = "disk"
    log.info("get_disk called")
    try:
        total_bytes, used_bytes, free_bytes = shutil.disk_usage("/")
        total_gb = round(total_bytes / 1_000_000_000, 1)
        used_gb = round(used_bytes / 1_000_000_000, 1)
        free_gb = round(free_bytes / 1_000_000_000, 1)
        used_percent = round((used_bytes / total_bytes) * 100)

        _emit_success(
            metric,
            f"Disk is {used_percent} percent used, with {free_gb} gigabytes free.",
            {
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": free_gb,
                "used_percent": used_percent,
            },
        )
    except Exception as error:
        log.exception("Unhandled error in get_disk")
        _emit_error(metric, "disk_error", str(error), "I couldn't read disk usage.")


def get_health():
    metric = "health"
    log.info("get_health called")
    try:
        issues = []
        data = {}

        raw_temperature = _safe_int(_read_text_file("/sys/class/thermal/thermal_zone0/temp"))
        if raw_temperature is not None:
            celsius = round(raw_temperature / 1000, 1)
            data["temperature_celsius"] = celsius
            if celsius >= 75:
                issues.append(f"temperature is high at {celsius} degrees Celsius")

        available_kb = _read_memory_kb("MemAvailable:")
        if available_kb is not None:
            available_mb = round(available_kb / 1024)
            data["memory_available_mb"] = available_mb
            if available_mb < 200:
                issues.append(f"memory is low with {available_mb} megabytes available")

        disk_total, disk_used, _ = shutil.disk_usage("/")
        disk_used_percent = round((disk_used / disk_total) * 100)
        data["disk_used_percent"] = disk_used_percent
        if disk_used_percent >= 90:
            issues.append(f"disk usage is high at {disk_used_percent} percent")

        data["issues"] = issues

        if not issues:
            _emit_success(metric, "The DevKit looks healthy.", data)
        elif len(issues) == 1:
            _emit_success(metric, f"I found one issue: {issues[0]}.", data)
        else:
            _emit_success(metric, f"I found {len(issues)} issues: {', '.join(issues[:2])}.", data)
    except Exception as error:
        log.exception("Unhandled error in get_health")
        _emit_error(metric, "health_error", str(error), "I couldn't run the DevKit health check.")


def get_all_stats():
    metric = "all_stats"
    log.info("get_all_stats called")
    try:
        cpu_percent = _read_cpu_usage_percent()
        raw_temperature = _safe_int(_read_text_file("/sys/class/thermal/thermal_zone0/temp"))
        temperature_celsius = round(raw_temperature / 1000, 1) if raw_temperature is not None else None
        total_memory_gb = _gb_from_kb(_read_memory_kb("MemTotal:"))
        available_memory_gb = _gb_from_kb(_read_memory_kb("MemAvailable:"))
        ssid = _run_command("iwgetid -r 2>/dev/null")
        total_bytes, used_bytes, free_bytes = shutil.disk_usage("/")
        free_disk_gb = round(free_bytes / 1_000_000_000, 1)
        disk_used_percent = round((used_bytes / total_bytes) * 100)

        data = {
            "cpu_used_percent": cpu_percent,
            "temperature_celsius": temperature_celsius,
            "memory_total_gb": total_memory_gb,
            "memory_available_gb": available_memory_gb,
            "wifi_connected": bool(ssid),
            "wifi_ssid": ssid or None,
            "disk_free_gb": free_disk_gb,
            "disk_used_percent": disk_used_percent,
        }

        spoken_parts = []
        if temperature_celsius is not None:
            spoken_parts.append(f"temperature is {temperature_celsius} degrees Celsius")
        if cpu_percent is not None:
            spoken_parts.append(f"CPU is {cpu_percent} percent used")
        if available_memory_gb is not None and total_memory_gb is not None:
            spoken_parts.append(f"memory has {available_memory_gb} gigabytes available")
        spoken_parts.append(f"disk is {disk_used_percent} percent used")
        spoken_parts.append(f"Wi-Fi is connected to {ssid}" if ssid else "Wi-Fi is not connected")

        _emit_success(metric, "DevKit snapshot: " + ", ".join(spoken_parts) + ".", data)
    except Exception as error:
        log.exception("Unhandled error in get_all_stats")
        _emit_error(metric, "all_stats_error", str(error), "I couldn't gather the DevKit snapshot.")


FUNCTION_REGISTRY = {
    "get_cpu": get_cpu,
    "get_memory": get_memory,
    "get_temperature": get_temperature,
    "get_uptime": get_uptime,
    "get_wifi": get_wifi,
    "get_disk": get_disk,
    "get_health": get_health,
    "get_all_stats": get_all_stats,
}


def main():
    if len(sys.argv) < 2:
        _emit_error("dispatch", "missing_function", "No function name was provided.", "No DevKit function was provided.")
        sys.exit(1)

    function_name = sys.argv[1]
    function_args = sys.argv[2:]
    function = FUNCTION_REGISTRY.get(function_name)

    if function is None:
        _emit_error(
            "dispatch",
            "unknown_function",
            f"Unknown function: {function_name}",
            "The requested DevKit function is not available.",
        )
        sys.exit(1)

    try:
        function(*function_args)
    except TypeError as error:
        log.exception("Invalid arguments for %s", function_name)
        _emit_error(
            function_name,
            "invalid_arguments",
            str(error),
            "The DevKit function received invalid arguments.",
        )
        sys.exit(1)
    except Exception as error:
        log.exception("Unhandled error while running %s", function_name)
        _emit_error(
            function_name,
            "unhandled_error",
            str(error),
            "The DevKit function failed unexpectedly.",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
