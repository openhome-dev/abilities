import sys
import os
import subprocess
import json
import datetime
import socket
import platform
import signal
import time
import math
import random
from devkit_utils.devkit_logging import web_logger as log

log.info("lights control functions")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LED_MODE_SCRIPT = os.path.join(BASE_DIR, "..", "..", "led_mode.py")
LED_PID_FILE = "/tmp/neopixel_effect.pid"
LED_STRIP_PIXELS = 24
LED_GPIO_PIN = 12
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_INVERT = False
LED_DEFAULT_BRIGHTNESS = 180
LED_CHANNEL = 0


def _read_file(path: str) -> str:
    try:
        with open(path, "r") as f:
            result = f.read().strip()
        return result
    except (FileNotFoundError, PermissionError) as e:
        return f"[error] {e}"


def _run_cmd(cmd: str) -> str:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() if result.returncode == 0 else f"[error] {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "[error] command timed out"
    except Exception as e:
        return f"[error] {e}"


def _print_result(data):
    if isinstance(data, dict):
        print(json.dumps(data, indent=2))
    elif isinstance(data, list):
        for item in data:
            print(item)
    else:
        print(data)


def _hex_to_rgb(hex_str):
    hex_str = str(hex_str).lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)
    if len(hex_str) != 6:
        raise ValueError("hex color must be 3 or 6 hex characters")
    return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))


def _clamp_int(value, minimum, maximum):
    return max(minimum, min(maximum, int(value)))


def _read_effect_pid():
    try:
        with open(LED_PID_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _is_pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _clear_pid_file_if_matches(pid=None):
    try:
        if not os.path.exists(LED_PID_FILE):
            return
        if pid is None:
            os.remove(LED_PID_FILE)
            return
        with open(LED_PID_FILE, "r") as f:
            existing = int(f.read().strip())
        if existing == pid:
            os.remove(LED_PID_FILE)
    except Exception:
        pass


def _kill_pid(pid, timeout=2.0):
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        return

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_pid_alive(pid):
            return
        time.sleep(0.05)

    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def _stop_running_led_effect():
    pid = _read_effect_pid()
    if pid and _is_pid_alive(pid):
        _kill_pid(pid)
    _clear_pid_file_if_matches()


def _init_strip(brightness=LED_DEFAULT_BRIGHTNESS):
    from rpi_ws281x import PixelStrip, ws as ws_mod
    strip = PixelStrip(
        LED_STRIP_PIXELS,
        LED_GPIO_PIN,
        LED_FREQ_HZ,
        LED_DMA,
        LED_INVERT,
        int(brightness),
        LED_CHANNEL,
        strip_type=ws_mod.WS2811_STRIP_GRB,
    )
    strip.begin()
    return strip


def _fill_strip(strip, color):
    from rpi_ws281x import Color
    r, g, b = color
    packed = Color(r, g, b)
    for i in range(LED_STRIP_PIXELS):
        strip.setPixelColor(i, packed)
    strip.show()


def _clear_strip(strip):
    _fill_strip(strip, (0, 0, 0))


def _scale_color(color, brightness):
    r, g, b = color
    scale = max(0.0, min(1.0, float(brightness) / 255.0))
    return int(r * scale), int(g * scale), int(b * scale)


def _spawn_effect(effect_name, *effect_args):
    log.info(f"spawn_effect: {effect_name} args={list(effect_args)}")
    _stop_running_led_effect()
    cmd = [sys.executable, os.path.abspath(__file__), "__led_effect_runner__", effect_name, *map(str, effect_args)]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=BASE_DIR,
    )
    with open(LED_PID_FILE, "w") as f:
        f.write(str(proc.pid))
    log.info(f"{effect_name} subprocess started pid={proc.pid}")
    print(f"{effect_name} started")


def _run_led_mode_script(mode):
    log.info(f"run_led_mode_script: mode={mode}")
    _stop_running_led_effect()
    cmd = [sys.executable, _LED_MODE_SCRIPT, mode]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=BASE_DIR,
    )
    with open(LED_PID_FILE, "w") as f:
        f.write(str(proc.pid))
    log.info(f"led_mode subprocess started mode={mode} pid={proc.pid}")
    print(f"LED mode -> {mode}")


def _should_stop_from_pid_mismatch():
    pid = _read_effect_pid()
    return pid not in (None, os.getpid())


def _effect_loop_should_continue(end_time):
    return time.time() < end_time and not _should_stop_from_pid_mismatch()


def get_stats(*requested):
    if not requested or "all" in requested:
        requested = ("cpu", "ram", "disk", "temp", "uptime", "load", "swap")

    collectors = {
        "cpu": _stat_cpu,
        "ram": _stat_ram,
        "disk": _stat_disk,
        "temp": _stat_temp,
        "uptime": _stat_uptime,
        "load": _stat_load,
        "swap": _stat_swap,
    }

    result = {}
    for key in requested:
        key = key.lower()
        if key in collectors:
            result[key] = collectors[key]()
        else:
            result[key] = f"[unknown stat] choices: {', '.join(collectors.keys())}"

    _print_result(result)


def _stat_cpu():
    try:
        load = _read_file("/proc/loadavg").split()
        return {
            "cores": os.cpu_count(),
            "load_1m": load[0] if load else "n/a",
            "load_5m": load[1] if len(load) > 1 else "n/a",
            "load_15m": load[2] if len(load) > 2 else "n/a",
            "governor": _read_file("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
            "freq_mhz": _read_file("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"),
        }
    except Exception as e:
        return {"error": str(e)}


def _stat_ram():
    try:
        info = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip()
                    if key in ("MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached"):
                        info[key] = val
        return info
    except Exception as e:
        return {"error": str(e)}


def _stat_disk():
    output = _run_cmd("df -h / --output=size,used,avail,pcent")
    lines = output.splitlines()
    if len(lines) >= 2:
        headers = lines[0].split()
        values = lines[1].split()
        return dict(zip(headers, values))
    return {"raw": output}


def _stat_temp():
    raw = _read_file("/sys/class/thermal/thermal_zone0/temp")
    try:
        celsius = int(raw) / 1000
        return {"celsius": celsius, "fahrenheit": round(celsius * 9 / 5 + 32, 1)}
    except ValueError:
        return {"raw": raw}


def _stat_uptime():
    raw = _read_file("/proc/uptime")
    try:
        seconds = float(raw.split()[0])
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        return {"seconds": seconds, "human": f"{days}d {hours}h {minutes}m"}
    except (ValueError, IndexError):
        return {"raw": raw}


def _stat_load():
    raw = _read_file("/proc/loadavg")
    parts = raw.split()
    return {
        "1min": parts[0], "5min": parts[1], "15min": parts[2],
        "running_procs": parts[3] if len(parts) > 3 else "n/a",
    } if parts else {"raw": raw}


def _stat_swap():
    try:
        info = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("Swap"):
                    parts = line.split(":")
                    info[parts[0].strip()] = parts[1].strip()
        return info
    except Exception as e:
        return {"error": str(e)}


def gpio_read(*pins):
    if not pins:
        print("[error] provide at least one GPIO pin number")
        return
    results = {}
    for pin in pins:
        gpio_path = f"/sys/class/gpio/gpio{pin}/value"
        if not os.path.exists(gpio_path):
            try:
                with open("/sys/class/gpio/export", "w") as f:
                    f.write(str(pin))
            except PermissionError:
                results[f"gpio{pin}"] = "[error] run with sudo or add user to gpio group"
                continue
            except OSError as e:
                results[f"gpio{pin}"] = f"[error] export failed: {e}"
                continue
        results[f"gpio{pin}"] = _read_file(gpio_path)
    _print_result(results)


def gpio_write(pin=None, value=None):
    if pin is None or value is None:
        print("[error] usage: gpio_write <pin> <0|1>")
        return
    gpio_dir = f"/sys/class/gpio/gpio{pin}"
    if not os.path.exists(gpio_dir):
        try:
            with open("/sys/class/gpio/export", "w") as f:
                f.write(str(pin))
        except (PermissionError, OSError) as e:
            print(f"[error] cannot export pin {pin}: {e}")
            return
    try:
        with open(f"{gpio_dir}/direction", "w") as f:
            f.write("out")
        with open(f"{gpio_dir}/value", "w") as f:
            f.write(str(value))
        print(f"gpio{pin} -> {value}")
    except (PermissionError, OSError) as e:
        print(f"[error] {e}")


def gpio_mode(pin=None, mode=None):
    if pin is None or mode is None:
        print("[error] usage: gpio_mode <pin> <in|out>")
        return
    if mode not in ("in", "out"):
        print("[error] mode must be 'in' or 'out'")
        return
    gpio_dir = f"/sys/class/gpio/gpio{pin}"
    if not os.path.exists(gpio_dir):
        try:
            with open("/sys/class/gpio/export", "w") as f:
                f.write(str(pin))
        except (PermissionError, OSError) as e:
            print(f"[error] cannot export pin {pin}: {e}")
            return
    try:
        with open(f"{gpio_dir}/direction", "w") as f:
            f.write(mode)
        print(f"gpio{pin} direction -> {mode}")
    except (PermissionError, OSError) as e:
        print(f"[error] {e}")


def set_brightness(value=None):
    bl_path = "/sys/class/backlight/rpi_backlight/brightness"
    if value is None:
        print(f"current brightness: {_read_file(bl_path)}")
        return
    try:
        val = int(value)
        if not 0 <= val <= 255:
            print("[error] value must be 0-255")
            return
        with open(bl_path, "w") as f:
            f.write(str(val))
        print(f"brightness -> {val}")
    except PermissionError:
        print("[error] run with sudo")
    except (ValueError, OSError) as e:
        print(f"[error] {e}")


def get_brightness():
    _print_result({
        "current": _read_file("/sys/class/backlight/rpi_backlight/brightness"),
        "max": _read_file("/sys/class/backlight/rpi_backlight/max_brightness"),
    })


def get_network(*interfaces):
    result = {}
    result["hostname"] = socket.gethostname()
    try:
        result["local_ip"] = socket.gethostbyname(socket.gethostname() + ".local")
    except socket.gaierror:
        ip_line = _run_cmd("hostname -I")
        result["local_ip"] = ip_line.split()[0] if ip_line else "n/a"
    iface_list = list(interfaces) if interfaces else (os.listdir("/sys/class/net/") if os.path.isdir("/sys/class/net/") else [])
    for iface in iface_list:
        idata = {}
        idata["state"] = _read_file(f"/sys/class/net/{iface}/operstate")
        idata["mac"] = _read_file(f"/sys/class/net/{iface}/address")
        ip_out = _run_cmd(f"ip -4 addr show {iface} 2>/dev/null | grep inet")
        if ip_out and "inet" in ip_out:
            idata["ipv4"] = ip_out.split()[1] if ip_out.split() else "n/a"
        result[iface] = idata
    _print_result(result)


def wifi_scan():
    output = _run_cmd("iwlist wlan0 scan 2>/dev/null | grep -E 'ESSID|Quality|Encryption'")
    print(output if output and "[error]" not in output else (output or "[info] no networks found or wlan0 not available"))


def wifi_status():
    _print_result({
        "ssid": _run_cmd("iwgetid -r 2>/dev/null") or "not connected",
        "signal": _run_cmd("iwconfig wlan0 2>/dev/null | grep -oP 'Signal level=\\K[^ ]+'"),
        "frequency": _run_cmd("iwconfig wlan0 2>/dev/null | grep -oP 'Frequency:\\K[^ ]+'"),
        "ip": _run_cmd("hostname -I").strip(),
    })


def get_processes(count="10"):
    print(_run_cmd(f"ps aux --sort=-%cpu | head -n {int(count) + 1}"))


def get_services(*services):
    if not services:
        print("[error] provide service name(s)")
        return
    result = {}
    for svc in services:
        result[svc] = {
            "status": _run_cmd(f"systemctl is-active {svc} 2>/dev/null"),
            "enabled": _run_cmd(f"systemctl is-enabled {svc} 2>/dev/null"),
        }
    _print_result(result)


def service_control(action=None, service=None):
    if not action or not service:
        print("[error] usage: service_control <start|stop|restart|enable|disable> <service>")
        return
    if action not in ("start", "stop", "restart", "enable", "disable"):
        print(f"[error] unknown action '{action}'. use: start, stop, restart, enable, disable")
        return
    output = _run_cmd(f"systemctl {action} {service} 2>&1")
    print(output if output else f"{service} -> {action} OK")


def get_pi_model():
    _print_result({
        "model": _read_file("/proc/device-tree/model"),
        "serial": _read_file("/proc/device-tree/serial-number"),
        "revision": _run_cmd("cat /proc/cpuinfo | grep Revision | awk '{print $3}'"),
        "architecture": platform.machine(),
        "os": _run_cmd("cat /etc/os-release | grep PRETTY_NAME | cut -d'\"' -f2"),
        "kernel": platform.release(),
    })


def get_storage():
    print(_run_cmd("lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL"))


def get_usb():
    print(_run_cmd("lsusb"))


def capture_image(output_path=None, width="1920", height="1080"):
    if output_path is None:
        output_path = f"/home/pi/capture_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    cmd = f"libcamera-still -o {output_path} --width {width} --height {height} --nopreview -t 1000 2>/dev/null"
    result = _run_cmd(cmd)
    if "[error]" in result:
        result = _run_cmd(f"raspistill -o {output_path} -w {width} -h {height} -t 1000 2>/dev/null")
    if os.path.exists(output_path):
        print(f"captured -> {output_path} ({os.path.getsize(output_path)} bytes)")
    else:
        print(f"[error] capture failed: {result}")


def led_control(led="0", state="1"):
    trigger_path = "/sys/class/leds/ACT/trigger"
    bright_path = "/sys/class/leds/ACT/brightness"
    try:
        if state in ("0", "1"):
            with open(trigger_path, "w") as f:
                f.write("none")
            with open(bright_path, "w") as f:
                f.write(state)
        else:
            with open(trigger_path, "w") as f:
                f.write(state)
        print(f"LED ACT -> {state}")
    except PermissionError:
        print("[error] run with sudo")
    except OSError as e:
        print(f"[error] {e}")


def stop_effect():
    """Kill any running user effect subprocess without clearing the strip."""
    log.info("stop_effect")
    _stop_running_led_effect()
    print("user effect stopped")


def neopixel_mode(mode="off"):
    log.info(f"neopixel_mode: mode={mode}")
    valid = ("off", "bot-speaking", "bot-listening", "bot-interrupted", "music-mode", "pause")
    if mode not in valid:
        log.error(f"neopixel_mode: unknown mode '{mode}'")
        print(f"[error] unknown mode '{mode}'. choices: {', '.join(valid)}")
        return
    _run_led_mode_script(mode)


def neopixel_off():
    log.info("neopixel_off")
    _stop_running_led_effect()
    try:
        strip = _init_strip()
        _clear_strip(strip)
        print("All LEDs off")
    except Exception as e:
        log.error(f"neopixel_off failed: {e}")
        print(f"[error] {e}")


def neopixel_solid(color="ff0000", brightness="180"):
    log.info(f"neopixel_solid: color={color} brightness={brightness}")
    _stop_running_led_effect()
    try:
        strip = _init_strip()
        _fill_strip(strip, _scale_color(_hex_to_rgb(color), _clamp_int(brightness, 0, 255)))
        print(f"Solid color #{color} brightness={brightness}")
    except Exception as e:
        log.error(f"neopixel_solid failed: {e}")
        print(f"[error] {e}")


def neopixel_set_pixel(pixel="0", color="ff0000"):
    log.info(f"neopixel_set_pixel: pixel={pixel} color={color}")
    _stop_running_led_effect()
    try:
        from rpi_ws281x import Color
        idx = int(pixel)
        if not 0 <= idx < LED_STRIP_PIXELS:
            print("[error] pixel must be 0-23")
            return
        strip = _init_strip()
        r, g, b = _hex_to_rgb(color)
        strip.setPixelColor(idx, Color(r, g, b))
        strip.show()
        print(f"Pixel {idx} -> #{color}")
    except Exception as e:
        log.error(f"neopixel_set_pixel failed: {e}")
        print(f"[error] {e}")


def neopixel_set_range(start="0", end="5", color="0000ff"):
    log.info(f"neopixel_set_range: start={start} end={end} color={color}")
    _stop_running_led_effect()
    try:
        from rpi_ws281x import Color
        s, e = int(start), int(end)
        s = max(0, min(LED_STRIP_PIXELS - 1, s))
        e = max(0, min(LED_STRIP_PIXELS - 1, e))
        strip = _init_strip()
        r, g, b = _hex_to_rgb(color)
        for i in range(s, e + 1):
            strip.setPixelColor(i, Color(r, g, b))
        strip.show()
        print(f"Pixels {s}-{e} -> #{color}")
    except Exception as e:
        log.error(f"neopixel_set_range failed: {e}")
        print(f"[error] {e}")


def neopixel_brightness(value="180"):
    log.info(f"neopixel_brightness: value={value}")
    _stop_running_led_effect()
    try:
        bri = _clamp_int(value, 0, 255)
        strip = _init_strip(brightness=bri)
        strip.show()
        print(f"LED brightness -> {bri}")
    except Exception as e:
        log.error(f"neopixel_brightness failed: {e}")
        print(f"[error] {e}")


def neopixel_rainbow(duration="5", speed="30"):
    _spawn_effect("rainbow", duration, speed)


def neopixel_breathe(color="0066ff", duration="5", speed="35"):
    _spawn_effect("breathe", color, duration, speed)


def neopixel_chase(color="ff0000", duration="5", speed="80"):
    _spawn_effect("chase", color, duration, speed)


def neopixel_fire(duration="5"):
    _spawn_effect("fire", duration)


def neopixel_sparkle(color="ffffff", duration="5", density="3"):
    _spawn_effect("sparkle", color, duration, density)


def neopixel_comet(color="0088ff", duration="5", speed="40"):
    _spawn_effect("comet", color, duration, speed)


def neopixel_color_wipe(color="00ff00", speed="50"):
    log.info(f"neopixel_color_wipe: color={color} speed={speed}")
    _stop_running_led_effect()
    try:
        from rpi_ws281x import Color
        strip = _init_strip()
        r, g, b = _hex_to_rgb(color)
        spd = max(10, int(speed))
        for i in range(LED_STRIP_PIXELS):
            strip.setPixelColor(i, Color(r, g, b))
            strip.show()
            time.sleep(spd / 1000.0)
        print(f"Color wipe #{color} done")
    except Exception as e:
        log.error(f"neopixel_color_wipe failed: {e}")
        print(f"[error] {e}")


def neopixel_gradient(color1="ff0000", color2="0000ff"):
    log.info(f"neopixel_gradient: color1={color1} color2={color2}")
    _stop_running_led_effect()
    try:
        from rpi_ws281x import Color
        r1, g1, b1 = _hex_to_rgb(color1)
        r2, g2, b2 = _hex_to_rgb(color2)
        strip = _init_strip()
        for i in range(LED_STRIP_PIXELS):
            t = i / float(LED_STRIP_PIXELS - 1)
            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)
            strip.setPixelColor(i, Color(r, g, b))
        strip.show()
        print(f"Gradient #{color1} -> #{color2}")
    except Exception as e:
        log.error(f"neopixel_gradient failed: {e}")
        print(f"[error] {e}")


def neopixel_strobe(color="ffffff", duration="3", speed="50"):
    _spawn_effect("strobe", color, duration, speed)


def neopixel_wave(color="0066ff", duration="5"):
    _spawn_effect("wave", color, duration)


def neopixel_police(duration="5"):
    _spawn_effect("police", duration)


def neopixel_candle(duration="10"):
    _spawn_effect("candle", duration)


def neopixel_music(duration="10"):
    _spawn_effect("music", duration)


def neopixel_sleep(duration="10"):
    _spawn_effect("sleep", duration)


def neopixel_speaking(duration="10"):
    _spawn_effect("speaking", duration)


def neopixel_listening(duration="10"):
    _spawn_effect("listening", duration)


def _wheel(pos, Color):
    pos = pos % 255
    if pos < 85:
        return Color(pos * 3, 255 - pos * 3, 0)
    elif pos < 170:
        pos -= 85
        return Color(255 - pos * 3, 0, pos * 3)
    else:
        pos -= 170
        return Color(0, pos * 3, 255 - pos * 3)


def _hsv_to_rgb(h, s, v):
    h = (h % 1.0) * 6.0
    i = int(h)
    f = h - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return int(r * 255), int(g * 255), int(b * 255)


def _run_effect_rainbow(duration="5", speed="30"):
    from rpi_ws281x import Color
    strip = _init_strip()
    end_time = time.time() + float(duration)
    spd = max(10, int(speed))
    j = 0
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                strip.setPixelColor(i, _wheel((i * 256 // LED_STRIP_PIXELS + j) & 255, Color))
            strip.show()
            time.sleep(spd / 1000.0)
            j = (j + 1) % 256
    finally:
        _clear_strip(strip)


def _run_effect_breathe(color="0066ff", duration="5", speed="35"):
    from rpi_ws281x import Color
    strip = _init_strip()
    r, g, b = _hex_to_rgb(color)
    end_time = time.time() + float(duration)
    spd = max(10, int(speed))
    phase = 0.0
    try:
        while _effect_loop_should_continue(end_time):
            breath = ((math.sin(phase) + 1.0) / 2.0) ** 2.2
            packed = Color(int(r * breath), int(g * breath), int(b * breath))
            for i in range(LED_STRIP_PIXELS):
                strip.setPixelColor(i, packed)
            strip.show()
            phase += 0.035
            time.sleep(spd / 1000.0)
    finally:
        _clear_strip(strip)


def _run_effect_chase(color="ff0000", duration="5", speed="80"):
    from rpi_ws281x import Color
    strip = _init_strip()
    r, g, b = _hex_to_rgb(color)
    end_time = time.time() + float(duration)
    spd = max(20, int(speed))
    step = 0
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                strip.setPixelColor(i, Color(r, g, b) if (i + step) % 3 == 0 else Color(0, 0, 0))
            strip.show()
            step = (step + 1) % 3
            time.sleep(spd / 1000.0)
    finally:
        _clear_strip(strip)


def _run_effect_fire(duration="5"):
    from rpi_ws281x import Color
    strip = _init_strip()
    end_time = time.time() + float(duration)
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                flicker = random.randint(0, 80)
                strip.setPixelColor(i, Color(max(0, 200 - flicker), max(0, 60 - flicker), 0))
            strip.show()
            time.sleep(0.05)
    finally:
        _clear_strip(strip)


def _run_effect_sparkle(color="ffffff", duration="5", density="3"):
    from rpi_ws281x import Color
    strip = _init_strip()
    r, g, b = _hex_to_rgb(color)
    dens = max(1, int(density))
    end_time = time.time() + float(duration)
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                strip.setPixelColor(i, Color(0, 0, 0))
            for _ in range(dens):
                idx = random.randint(0, LED_STRIP_PIXELS - 1)
                strip.setPixelColor(idx, Color(r, g, b))
            strip.show()
            time.sleep(0.08)
    finally:
        _clear_strip(strip)


def _run_effect_comet(color="0088ff", duration="5", speed="40"):
    from rpi_ws281x import Color
    strip = _init_strip()
    r, g, b = _hex_to_rgb(color)
    end_time = time.time() + float(duration)
    spd = max(10, int(speed))
    tail_len = 6
    pos = 0
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                strip.setPixelColor(i, Color(0, 0, 0))
            for t in range(tail_len):
                idx = (pos - t) % LED_STRIP_PIXELS
                fade = (1.0 - (t / tail_len)) ** 2
                strip.setPixelColor(idx, Color(int(r * fade), int(g * fade), int(b * fade)))
            strip.show()
            pos = (pos + 1) % LED_STRIP_PIXELS
            time.sleep(spd / 1000.0)
    finally:
        _clear_strip(strip)


def _run_effect_strobe(color="ffffff", duration="3", speed="50"):
    from rpi_ws281x import Color
    strip = _init_strip()
    r, g, b = _hex_to_rgb(color)
    end_time = time.time() + float(duration)
    spd = max(20, int(speed))
    on = True
    try:
        while _effect_loop_should_continue(end_time):
            packed = Color(r, g, b) if on else Color(0, 0, 0)
            for i in range(LED_STRIP_PIXELS):
                strip.setPixelColor(i, packed)
            strip.show()
            on = not on
            time.sleep(spd / 1000.0)
    finally:
        _clear_strip(strip)


def _run_effect_wave(color="0066ff", duration="5"):
    from rpi_ws281x import Color
    strip = _init_strip()
    r, g, b = _hex_to_rgb(color)
    end_time = time.time() + float(duration)
    phase = 0.0
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                brightness = (math.sin(phase + i * math.pi * 2 / LED_STRIP_PIXELS) + 1.0) / 2.0
                strip.setPixelColor(i, Color(int(r * brightness), int(g * brightness), int(b * brightness)))
            strip.show()
            phase += 0.1
            time.sleep(0.03)
    finally:
        _clear_strip(strip)


def _run_effect_police(duration="5"):
    from rpi_ws281x import Color
    strip = _init_strip()
    end_time = time.time() + float(duration)
    flip = True
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                if flip:
                    c = Color(255, 0, 0) if i < LED_STRIP_PIXELS // 2 else Color(0, 0, 255)
                else:
                    c = Color(0, 0, 255) if i < LED_STRIP_PIXELS // 2 else Color(255, 0, 0)
                strip.setPixelColor(i, c)
            strip.show()
            flip = not flip
            time.sleep(0.15)
    finally:
        _clear_strip(strip)


def _run_effect_candle(duration="10"):
    from rpi_ws281x import Color
    strip = _init_strip()
    end_time = time.time() + float(duration)
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                flicker = random.randint(0, 50)
                strip.setPixelColor(i, Color(max(0, 255 - flicker), max(0, 100 - flicker), max(0, 20 - flicker // 2)))
            strip.show()
            time.sleep(random.uniform(0.03, 0.12))
    finally:
        _clear_strip(strip)


def _run_effect_music(duration="10"):
    from rpi_ws281x import Color
    strip = _init_strip()
    end_time = time.time() + float(duration)
    t = 0.0
    base_hue = 0.62
    beat_phase = 0.0
    rot = 0.0
    leds_per_side = 6
    sides = 4
    try:
        while _effect_loop_should_continue(end_time):
            beat = ((math.sin(beat_phase) + 1.0) / 2.0) ** 5.0
            global_v = max(0.0, min(1.0, 0.2 + 0.55 * beat))
            hot_side = int(rot) % sides
            hot_frac = rot - int(rot)
            for side in range(sides):
                side_start = side * leds_per_side
                if side == hot_side:
                    side_boost = 1.0 - hot_frac
                elif side == (hot_side + 1) % sides:
                    side_boost = hot_frac
                else:
                    side_boost = 0.0
                side_v = max(0.0, min(1.0, global_v + 0.35 * side_boost))
                side_h = base_hue + side * 0.04
                for j in range(leds_per_side):
                    i = side_start + j
                    grad = 0.75 + (j / (leds_per_side - 1)) * 0.25
                    shimmer = 0.10 * math.sin(t + j * 0.9 + side * 1.2)
                    v = max(0.0, min(1.0, side_v * grad + shimmer))
                    h = side_h + j * 0.01 + 0.02 * math.sin(t + side)
                    r, g, b = _hsv_to_rgb(h, 0.95, v)
                    strip.setPixelColor(i, Color(r, int(g * 0.80), b))
            strip.show()
            t += 0.10
            base_hue = (base_hue + 0.0025) % 1.0
            beat_phase += 0.13
            rot = (rot + 0.1) % 4.0
            time.sleep(0.02)
    finally:
        _clear_strip(strip)


def _run_effect_sleep(duration="10"):
    from rpi_ws281x import Color
    strip = _init_strip()
    end_time = time.time() + float(duration)
    phase = 0.0
    try:
        while _effect_loop_should_continue(end_time):
            breath = ((math.sin(phase) + 1.0) / 2.0) ** 2.2
            brightness = 0.28 + breath * (1.00 - 0.28)
            packed = Color(int(255 * brightness), int(90 * brightness), 0)
            for i in range(LED_STRIP_PIXELS):
                strip.setPixelColor(i, packed)
            strip.show()
            phase += 0.035
            time.sleep(0.03)
    finally:
        _clear_strip(strip)


def _run_effect_speaking(duration="10"):
    from rpi_ws281x import Color
    PALETTE = [
        (40, 90, 255), (35, 140, 220), (45, 190, 140),
        (70, 80, 210), (110, 55, 220), (70, 65, 255),
    ]
    def palette_color(t):
        i = int(t) % len(PALETTE)
        j = (i + 1) % len(PALETTE)
        f = t - int(t)
        c1, c2 = PALETTE[i], PALETTE[j]
        return (
            int(c1[0] + (c2[0] - c1[0]) * f),
            int(c1[1] + (c2[1] - c1[1]) * f),
            int(c1[2] + (c2[2] - c1[2]) * f),
        )
    strip = _init_strip()
    end_time = time.time() + float(duration)
    rng = random.Random()
    color_t = 0.0
    pulse = 0.35
    target = 0.80
    frames_left = 0
    try:
        while _effect_loop_should_continue(end_time):
            if frames_left <= 0:
                r = rng.random()
                if r < 0.30:
                    target = rng.uniform(0.20, 0.35)
                    frames_left = rng.randint(5, 9)
                elif r < 0.80:
                    target = rng.uniform(0.45, 0.70)
                    frames_left = rng.randint(4, 8)
                else:
                    target = rng.uniform(0.80, 1.00)
                    frames_left = rng.randint(3, 6)
            frames_left -= 1
            pulse += (target - pulse) * 0.55
            pulse = max(0.0, min(1.0, pulse))
            brightness = 0.05 + pulse * 0.95
            for i in range(LED_STRIP_PIXELS):
                rc, gc, bc = palette_color(color_t + i * 0.25)
                strip.setPixelColor(i, Color(int(rc * brightness), int(gc * 0.75 * brightness), int(bc * brightness)))
            strip.show()
            color_t += 0.015
            time.sleep(0.03)
    finally:
        _clear_strip(strip)


def _run_effect_listening(duration="10"):
    from rpi_ws281x import Color
    strip = _init_strip()
    end_time = time.time() + float(duration)
    hue = 140
    try:
        while _effect_loop_should_continue(end_time):
            for i in range(LED_STRIP_PIXELS):
                r, g, b = _hex_to_rgb(f"{(hue+i*5)%255:02x}00ff") if False else (0,0,0)
            for i in range(LED_STRIP_PIXELS):
                pos = (hue + int(i * 5)) % 255
                if pos < 85:
                    r, g, b = pos * 3, 255 - pos * 3, 0
                elif pos < 170:
                    pos -= 85
                    r, g, b = 255 - pos * 3, 0, pos * 3
                else:
                    pos -= 170
                    r, g, b = 0, pos * 3, 255 - pos * 3
                strip.setPixelColor(i, Color(r, int(g * 0.75), b))
            strip.show()
            hue = (hue + 1) % 255
            time.sleep(0.05)
    finally:
        _clear_strip(strip)


def _run_named_effect(effect_name, args):
    log.info(f"_run_named_effect: {effect_name} args={args} pid={os.getpid()}")
    with open(LED_PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    runners = {
        "rainbow": _run_effect_rainbow,
        "breathe": _run_effect_breathe,
        "chase": _run_effect_chase,
        "fire": _run_effect_fire,
        "sparkle": _run_effect_sparkle,
        "comet": _run_effect_comet,
        "strobe": _run_effect_strobe,
        "wave": _run_effect_wave,
        "police": _run_effect_police,
        "candle": _run_effect_candle,
        "music": _run_effect_music,
        "sleep": _run_effect_sleep,
        "speaking": _run_effect_speaking,
        "listening": _run_effect_listening,
    }
    if effect_name not in runners:
        log.error(f"_run_named_effect: unknown runner '{effect_name}'")
        raise ValueError(f"unknown effect runner: {effect_name}")
    try:
        runners[effect_name](*args)
    except Exception as e:
        log.error(f"_run_named_effect: {effect_name} crashed: {e}")
        raise
    finally:
        log.info(f"_run_named_effect: {effect_name} ended pid={os.getpid()}")
        _clear_pid_file_if_matches(os.getpid())


def shutdown(delay="0"):
    print(f"shutting down in {delay} minute(s)...")
    os.system(f"sudo shutdown -h +{delay}")


def reboot(delay="0"):
    print(f"rebooting in {delay} minute(s)...")
    os.system(f"sudo shutdown -r +{delay}")


def list_cron():
    print(_run_cmd("crontab -l 2>/dev/null") or "[info] no crontab entries")


def add_cron(schedule=None, command=None):
    if not schedule or not command:
        print("[error] usage: add_cron '<cron_schedule>' '<command>'")
        return
    existing = _run_cmd("crontab -l 2>/dev/null")
    new_entry = f"{schedule} {command}"
    full = f"{existing}\n{new_entry}" if existing and "[error]" not in existing else new_entry
    result = _run_cmd(f'echo "{full}" | crontab -')
    print(result if result else f"added: {new_entry}")


def tail_log(log_path="/var/log/syslog", lines="20"):
    print(_run_cmd(f"tail -n {lines} {log_path}"))


def disk_usage(path="/"):
    print(_run_cmd(f"du -sh {path} 2>/dev/null"))


FUNCTION_REGISTRY = {
    "get_stats": get_stats,
    "gpio_read": gpio_read,
    "gpio_write": gpio_write,
    "gpio_mode": gpio_mode,
    "set_brightness": set_brightness,
    "get_brightness": get_brightness,
    "get_network": get_network,
    "wifi_scan": wifi_scan,
    "wifi_status": wifi_status,
    "get_processes": get_processes,
    "get_services": get_services,
    "service_control": service_control,
    "get_pi_model": get_pi_model,
    "get_storage": get_storage,
    "get_usb": get_usb,
    "capture_image": capture_image,
    "led_control": led_control,
    "stop_effect": stop_effect,
    "neopixel_mode": neopixel_mode,
    "neopixel_off": neopixel_off,
    "neopixel_solid": neopixel_solid,
    "neopixel_set_pixel": neopixel_set_pixel,
    "neopixel_set_range": neopixel_set_range,
    "neopixel_brightness": neopixel_brightness,
    "neopixel_rainbow": neopixel_rainbow,
    "neopixel_breathe": neopixel_breathe,
    "neopixel_chase": neopixel_chase,
    "neopixel_fire": neopixel_fire,
    "neopixel_sparkle": neopixel_sparkle,
    "neopixel_comet": neopixel_comet,
    "neopixel_color_wipe": neopixel_color_wipe,
    "neopixel_gradient": neopixel_gradient,
    "neopixel_strobe": neopixel_strobe,
    "neopixel_wave": neopixel_wave,
    "neopixel_police": neopixel_police,
    "neopixel_candle": neopixel_candle,
    "neopixel_music": neopixel_music,
    "neopixel_sleep": neopixel_sleep,
    "neopixel_speaking": neopixel_speaking,
    "neopixel_listening": neopixel_listening,
    "shutdown": shutdown,
    "reboot": reboot,
    "list_cron": list_cron,
    "add_cron": add_cron,
    "tail_log": tail_log,
    "disk_usage": disk_usage,
}


def list_functions():
    print("=" * 60)
    print("  AVAILABLE FUNCTIONS")
    print("=" * 60)
    for name, func in FUNCTION_REGISTRY.items():
        doc = (func.__doc__ or "").strip().split("\n")
        summary = doc[0] if doc else "no description"
        print(f"\n  {name}")
        print(f"    {summary}")
    print()


FUNCTION_REGISTRY["list_functions"] = list_functions


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "__led_effect_runner__":
        if len(sys.argv) < 3:
            print("[error] missing effect name")
            sys.exit(1)
        effect_name = sys.argv[2]
        effect_args = sys.argv[3:]
        try:
            _run_named_effect(effect_name, effect_args)
            sys.exit(0)
        except Exception as e:
            print(f"[error] {e}")
            sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python3 pifunctions.py <function_name> [args...]")
        print("       python3 pifunctions.py list_functions")
        sys.exit(1)

    func_name = sys.argv[1]
    func_args = sys.argv[2:]

    if func_name in ("--help", "-h"):
        list_functions()
        sys.exit(0)

    if func_name not in FUNCTION_REGISTRY:
        print(f"[error] unknown function '{func_name}'")
        print("[hint] run: python3 pifunctions.py list_functions")
        sys.exit(1)

    func = FUNCTION_REGISTRY[func_name]
    try:
        func(*func_args)
        sys.exit(0)
    except TypeError as e:
        print(f"[error] wrong arguments for '{func_name}': {e}")
        sys.exit(1)
    except Exception as e:
        print(f"[error] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
