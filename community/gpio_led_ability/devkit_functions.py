"""
GPIO LED Controller — devkit_functions.py
Runs on the OpenHome DevKit (Raspberry Pi 4).

Wiring:
  LED anode (+) --> 330Ω resistor --> GPIO 17 (BCM)
  LED cathode (-) --> GND (pin 6 or any GND)

Uses gpiozero for clean, safe GPIO access.
"""

import json
import sys
import time
from devkit_utils.devkit_logging import web_logger as log


# ---------------------------------------------------------------------------
# GPIO setup — wrapped in try/except so import failures speak clearly
# ---------------------------------------------------------------------------
try:
    from gpiozero import LED
    from gpiozero import Device
    _GPIO_AVAILABLE = True
except ImportError as _import_err:
    _GPIO_AVAILABLE = False
    _IMPORT_ERROR = str(_import_err)
    log.error("gpiozero import failed: %s", _import_err)

LED_PIN = 17  # BCM pin number — change if your wiring is different


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _emit_success(action, spoken, data=None):
    payload = {
        "success": True,
        "action": action,
        "spoken_response": spoken,
        "data": data or {},
        "error": None,
    }
    serialized = json.dumps(payload)
    log.info("stdout payload: %s", serialized)
    print(serialized)


def _emit_error(action, code, message, spoken):
    log.error("%s failed [%s]: %s", action, code, message)
    payload = {
        "success": False,
        "action": action,
        "spoken_response": spoken,
        "data": {},
        "error": {
            "code": code,
            "message": message,
        },
    }
    serialized = json.dumps(payload)
    log.info("stdout payload: %s", serialized)
    print(serialized)


def _check_gpio():
    """Returns (True, led_instance) or (False, None) with an error emitted."""
    if not _GPIO_AVAILABLE:
        _emit_error(
            "gpio_check",
            "import_error",
            _IMPORT_ERROR,
            "The gpiozero library is not available. Make sure it is listed in requirements.txt.",
        )
        return False, None
    try:
        led = LED(LED_PIN)
        return True, led
    except Exception as err:
        _emit_error(
            "gpio_check",
            "gpio_init_error",
            str(err),
            f"I couldn't initialise GPIO pin {LED_PIN}. Check your wiring.",
        )
        return False, None


# ---------------------------------------------------------------------------
# LED functions
# ---------------------------------------------------------------------------

def led_on():
    """Turn the LED on."""
    log.info("led_on called")
    ok, led = _check_gpio()
    if not ok:
        return
    try:
        led.on()
        log.info("LED on GPIO %d turned ON", LED_PIN)
        _emit_success(
            "led_on",
            f"LED on GPIO pin {LED_PIN} is now on.",
            {"pin": LED_PIN, "state": "on"},
        )
    except Exception as err:
        log.exception("Unhandled error in led_on")
        _emit_error("led_on", "led_on_error", str(err), "I couldn't turn the LED on.")
    finally:
        led.close()


def led_off():
    """Turn the LED off."""
    log.info("led_off called")
    ok, led = _check_gpio()
    if not ok:
        return
    try:
        led.off()
        log.info("LED on GPIO %d turned OFF", LED_PIN)
        _emit_success(
            "led_off",
            f"LED on GPIO pin {LED_PIN} is now off.",
            {"pin": LED_PIN, "state": "off"},
        )
    except Exception as err:
        log.exception("Unhandled error in led_off")
        _emit_error("led_off", "led_off_error", str(err), "I couldn't turn the LED off.")
    finally:
        led.close()


def led_blink(count_str="3"):
    """
    Blink the LED a given number of times.
    count_str is always a string coming from sys.argv — cast here.
    """
    log.info("led_blink called with count_str=%s", count_str)

    # Safely cast the count argument
    try:
        count = max(1, min(int(count_str), 20))
    except (ValueError, TypeError):
        count = 3

    ok, led = _check_gpio()
    if not ok:
        return
    try:
        for i in range(count):
            led.on()
            time.sleep(0.4)
            led.off()
            time.sleep(0.3)
            log.info("Blink %d/%d", i + 1, count)

        log.info("LED blinked %d times on GPIO %d", count, LED_PIN)
        times_word = "time" if count == 1 else "times"
        _emit_success(
            "led_blink",
            f"LED blinked {count} {times_word}.",
            {"pin": LED_PIN, "blink_count": count},
        )
    except Exception as err:
        log.exception("Unhandled error in led_blink")
        _emit_error("led_blink", "led_blink_error", str(err), "I couldn't blink the LED.")
    finally:
        led.close()


def led_status():
    """Report the current state of the LED pin."""
    log.info("led_status called")
    ok, led = _check_gpio()
    if not ok:
        return
    try:
        state = "on" if led.is_lit else "off"
        log.info("LED status on GPIO %d: %s", LED_PIN, state)
        _emit_success(
            "led_status",
            f"The LED on GPIO pin {LED_PIN} is currently {state}.",
            {"pin": LED_PIN, "state": state},
        )
    except Exception as err:
        log.exception("Unhandled error in led_status")
        _emit_error("led_status", "led_status_error", str(err), "I couldn't check the LED status.")
    finally:
        led.close()


# ---------------------------------------------------------------------------
# Registry & entrypoint
# ---------------------------------------------------------------------------

FUNCTION_REGISTRY = {
    "led_on": led_on,
    "led_off": led_off,
    "led_blink": led_blink,
    "led_status": led_status,
}


def main():
    if len(sys.argv) < 2:
        _emit_error(
            "dispatch",
            "missing_function",
            "No function name provided.",
            "No LED function was specified.",
        )
        sys.exit(1)

    function_name = sys.argv[1]
    function_args = sys.argv[2:]
    function = FUNCTION_REGISTRY.get(function_name)

    if function is None:
        _emit_error(
            "dispatch",
            "unknown_function",
            f"Unknown function: {function_name}",
            f"The LED function '{function_name}' is not available.",
        )
        sys.exit(1)

    try:
        function(*function_args)
    except TypeError as err:
        log.exception("Invalid arguments for %s", function_name)
        _emit_error(
            function_name,
            "invalid_arguments",
            str(err),
            "The LED function received invalid arguments.",
        )
        sys.exit(1)
    except Exception as err:
        log.exception("Unhandled error in %s", function_name)
        _emit_error(
            function_name,
            "unhandled_error",
            str(err),
            "The LED function failed unexpectedly.",
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
