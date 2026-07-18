import hashlib
import re
import time

import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker


# ============================================================
# SENTINEL CONFIGURATION
# ============================================================

INTRO_PROMPT = (
    "Buddy DevOps consultant online. "
    "Tell me a website or API to inspect. "
    "For example, say check example dot com. "
    "Say help for available commands, or stop to exit."
)

EXIT_PROMPT = (
    "Buddy monitoring session complete. "
    "All diagnostic checks have been closed safely. Goodbye."
)

HELP_PROMPT = (
    "I can check website and API availability, HTTP status codes, "
    "response time, DNS failures, SSL issues, authentication errors, "
    "missing endpoints, server errors, and gateway failures. "
    "Say check followed by a website or API address."
)

EXIT_PHRASES = (
    "done",
    "stop",
    "quit",
    "exit",
    "goodbye",
    "bye",
    "cancel",
    "finish",
    "end session",
    "that's all",
    "that is all",
    "i'm done",
    "im done",
)

HELP_PHRASES = (
    "help",
    "commands",
    "options",
    "what can you do",
    "how does this work",
)

DEFAULT_TIMEOUT = 7
SLOW_THRESHOLD_MS = 1200
VERY_SLOW_THRESHOLD_MS = 3000


# ============================================================
# PREDICTABLE HACKATHON DEMO TARGETS
# ============================================================

DEMO_SITES = {
    "my portfolio": {
        "target": "https://portfolio.demo",
        "up": True,
        "code": 200,
        "latency": 180,
        "content_type": "text/html",
        "server": "nginx",
        "category": "healthy",
        "cause": None,
        "recommendation": None,
    },
    "portfolio": {
        "target": "https://portfolio.demo",
        "up": True,
        "code": 200,
        "latency": 180,
        "content_type": "text/html",
        "server": "nginx",
        "category": "healthy",
        "cause": None,
        "recommendation": None,
    },
    "company site": {
        "target": "https://company.demo",
        "up": False,
        "code": 500,
        "latency": 950,
        "content_type": "text/html",
        "server": "nginx",
        "category": "server",
        "cause": "The server returned an internal server error",
        "recommendation": (
            "Check application logs, recent deployments, database connectivity, "
            "and server resource utilization."
        ),
    },
    "carecloud": {
        "target": "https://carecloud.demo",
        "up": False,
        "code": 500,
        "latency": 840,
        "content_type": "application/json",
        "server": "cloud gateway",
        "category": "server",
        "cause": "The backend service returned an internal server error",
        "recommendation": (
            "Inspect backend application logs, database connections, "
            "and the latest deployment."
        ),
    },
    "staging server": {
        "target": "https://staging.demo",
        "up": False,
        "code": None,
        "latency": None,
        "content_type": None,
        "server": None,
        "category": "dns",
        "cause": "DNS resolution failed because the hostname could not be resolved",
        "recommendation": (
            "Verify the DNS record, domain spelling, nameservers, "
            "and recent DNS configuration changes."
        ),
    },
}


DNS_ERROR_SIGNATURES = (
    "getaddrinfo failed",
    "name or service not known",
    "nodename nor servname",
    "temporary failure in name resolution",
    "failed to resolve",
    "no address associated with hostname",
    "name resolution",
)


# ============================================================
# INPUT HANDLING
# ============================================================

def clean_spoken_input(value):
    cleaned = value.strip()

    patterns = (
        r"^(please\s+)?check\s+(whether\s+)?",
        r"^(please\s+)?inspect\s+",
        r"^(please\s+)?monitor\s+",
        r"^(please\s+)?diagnose\s+",
        r"^(please\s+)?test\s+",
        r"^(please\s+)?tell me about\s+",
        r"^(please\s+)?check the health of\s+",
        r"^(please\s+)?is\s+",
    )

    for pattern in patterns:
        cleaned = re.sub(
            pattern,
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    cleaned = re.sub(
        r"\s+(website|site|api)\s+(up|down|working|healthy)\??$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s+dot\s+",
        ".",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s+slash\s+",
        "/",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s+colon\s+",
        ":",
        cleaned,
        flags=re.IGNORECASE,
    )

    return cleaned.strip(" ?.,!")


def normalize_phrase(value):
    normalized = re.sub(
        r"[^a-z0-9\s']",
        " ",
        value.lower(),
    )

    return " ".join(normalized.split())


def is_exit_request(value):
    return normalize_phrase(value) in EXIT_PHRASES


def is_help_request(value):
    return normalize_phrase(value) in HELP_PHRASES


def normalize_url(site):
    """
    Convert a spoken website or API address into a usable URL.
    This version does not use ..
    """

    cleaned = clean_spoken_input(site)

    if not cleaned:
        return None

    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned

    try:
        after_scheme = cleaned.split("://", 1)[-1]

        host_port = after_scheme.split("/", 1)[0]
        host_port = host_port.split("?", 1)[0]
        host_port = host_port.split("#", 1)[0]

        if host_port.startswith("["):
            closing_bracket = host_port.find("]")

            if closing_bracket == -1:
                return None

            hostname = host_port[1:closing_bracket]
        else:
            hostname = host_port.split(":", 1)[0]

        hostname = hostname.strip().lower()

        if not hostname:
            return None

        if " " in hostname:
            return None

        is_localhost = hostname == "localhost"

        parts = hostname.split(".")

        is_ipv4 = (
            len(parts) == 4
            and all(
                part.isdigit()
                and 0 <= int(part) <= 255
                for part in parts
            )
        )

        is_domain = (
            "." in hostname
            and not hostname.startswith(".")
            and not hostname.endswith(".")
        )

        if not (is_localhost or is_ipv4 or is_domain):
            return None

        return cleaned

    except Exception:
        return None


def stable_target_key(target):
    digest = hashlib.sha256(
        target.lower().encode("utf-8")
    ).hexdigest()[:20]

    return "buddy" + digest


# ============================================================
# HEALTH CLASSIFICATION
# ============================================================

def latency_health(latency_ms):
    if latency_ms is None:
        return "unknown"

    if latency_ms < 500:
        return "healthy"

    if latency_ms < SLOW_THRESHOLD_MS:
        return "acceptable"

    if latency_ms < VERY_SLOW_THRESHOLD_MS:
        return "slow"

    return "critically slow"


def classify_http_response(response):
    code = response.status_code

    if 200 <= code < 300:
        return {
            "up": True,
            "category": "healthy",
            "cause": None,
            "recommendation": None,
        }

    if 300 <= code < 400:
        return {
            "up": True,
            "category": "redirect",
            "cause": "The endpoint is responding with a redirect",
            "recommendation": (
                "Verify that the redirect destination is expected "
                "and that no redirect loop exists."
            ),
        }

    if code == 400:
        return {
            "up": False,
            "category": "request",
            "cause": "The server rejected the request as malformed",
            "recommendation": (
                "Check the URL, query parameters, headers, and payload format."
            ),
        }

    if code == 401:
        return {
            "up": False,
            "category": "authentication",
            "cause": (
                "Authentication is required or the supplied credentials are invalid"
            ),
            "recommendation": (
                "Verify the API key, access token, authorization header, "
                "and token expiration."
            ),
        }

    if code == 403:
        return {
            "up": False,
            "category": "authorization",
            "cause": "The server is reachable but access is forbidden",
            "recommendation": (
                "Check user permissions, IP allowlists, firewall rules, "
                "and API access policies."
            ),
        }

    if code == 404:
        return {
            "up": False,
            "category": "endpoint",
            "cause": (
                "The server is reachable but the requested endpoint was not found"
            ),
            "recommendation": (
                "Verify the URL path, API version, route configuration, "
                "and whether the endpoint was renamed or removed."
            ),
        }

    if code == 405:
        return {
            "up": False,
            "category": "method",
            "cause": (
                "The endpoint does not allow the HTTP method used for this check"
            ),
            "recommendation": (
                "Confirm whether the endpoint expects GET, POST, "
                "HEAD, or another method."
            ),
        }

    if code == 408:
        return {
            "up": False,
            "category": "timeout",
            "cause": "The server timed out while processing the request",
            "recommendation": (
                "Inspect slow dependencies, database queries, "
                "upstream services, and server resources."
            ),
        }

    if code == 429:
        return {
            "up": False,
            "category": "rate limit",
            "cause": (
                "The endpoint is rejecting requests because of rate limiting"
            ),
            "recommendation": (
                "Check rate-limit headers, reduce request frequency, "
                "or review API quota settings."
            ),
        }

    if code == 500:
        return {
            "up": False,
            "category": "server",
            "cause": "The application returned an internal server error",
            "recommendation": (
                "Inspect application logs, recent deployments, "
                "database connectivity, exceptions, and server resources."
            ),
        }

    if code == 502:
        return {
            "up": False,
            "category": "gateway",
            "cause": (
                "The gateway received an invalid response from an upstream service"
            ),
            "recommendation": (
                "Check the reverse proxy, load balancer, upstream service health, "
                "ports, and network connectivity."
            ),
        }

    if code == 503:
        return {
            "up": False,
            "category": "availability",
            "cause": "The service is temporarily unavailable",
            "recommendation": (
                "Check maintenance mode, autoscaling, overloaded instances, "
                "service discovery, and dependency health."
            ),
        }

    if code == 504:
        return {
            "up": False,
            "category": "gateway timeout",
            "cause": (
                "The gateway timed out while waiting for an upstream service"
            ),
            "recommendation": (
                "Inspect upstream latency, application timeouts, "
                "database queries, and network connectivity."
            ),
        }

    if 400 <= code < 500:
        return {
            "up": False,
            "category": "client",
            "cause": "The endpoint returned client error " + str(code),
            "recommendation": (
                "Review the URL, request headers, authentication, "
                "parameters, and payload."
            ),
        }

    return {
        "up": False,
        "category": "server",
        "cause": "The endpoint returned server error " + str(code),
        "recommendation": (
            "Inspect server logs, dependencies, recent deployments, "
            "and infrastructure health."
        ),
    }


# ============================================================
# OPENHOME CAPABILITY
# ============================================================

class DevopsintrenchesCapability(MatchingCapability):
    worker = None
    capability_worker = None

    #{{register capability}}

    def call(self, worker):
        self.worker = worker

        # Important: pass the capability instance here.
        self.capability_worker = CapabilityWorker(self)

        self.worker.session_tasks.create(self.run())

    # --------------------------------------------------------
    # LOGGING
    # --------------------------------------------------------

    def log_info(self, message):
        try:
            self.worker.editor_logging_handler.info(
                "[buddy] " + message
            )
        except Exception:
            pass

    def log_warning(self, message):
        try:
            self.worker.editor_logging_handler.warning(
                "[buddy] " + message
            )
        except Exception:
            pass

    def log_error(self, message):
        try:
            self.worker.editor_logging_handler.error(
                "[Sentinel] " + message
            )
        except Exception:
            pass

    # --------------------------------------------------------
    # FAILURE RESULT
    # --------------------------------------------------------

    def failure_result(
        self,
        target,
        category,
        cause,
        recommendation,
    ):
        return {
            "target": target,
            "final_url": target,
            "up": False,
            "code": None,
            "latency": None,
            "health": "unreachable",
            "category": category,
            "cause": cause,
            "recommendation": recommendation,
            "content_type": None,
            "server": None,
            "redirected": False,
            "checked_at": time.time(),
        }

    # --------------------------------------------------------
    # DIAGNOSTIC ENGINE
    # --------------------------------------------------------

    def diagnose(self, site):
        cleaned_target = clean_spoken_input(site)
        target_lower = cleaned_target.lower()

        # Predictable hackathon demo checks.
        for demo_key in DEMO_SITES:
            if demo_key == target_lower:
                result = dict(DEMO_SITES[demo_key])

                result["health"] = latency_health(
                    result.get("latency")
                )

                result["checked_at"] = time.time()
                result["final_url"] = result.get("target")
                result["redirected"] = False

                return result

        url = normalize_url(cleaned_target)

        if not url:
            return {
                "target": cleaned_target,
                "final_url": None,
                "up": False,
                "code": None,
                "latency": None,
                "health": "unknown",
                "category": "input",
                "cause": (
                    "I could not identify a valid website hostname "
                    "or API URL"
                ),
                "recommendation": (
                    "Provide a domain such as example dot com "
                    "or a complete HTTPS API URL."
                ),
                "content_type": None,
                "server": None,
                "checked_at": time.time(),
                "redirected": False,
            }

        self.log_info("Checking target: " + url)

        headers = {
            "User-Agent": "Buddy-DevOps-Health-Checker/1.0",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        }

        try:
            start_time = time.perf_counter()

            response = requests.get(
                url,
                timeout=DEFAULT_TIMEOUT,
                headers=headers,
                allow_redirects=True,
            )

            latency = round(
                (time.perf_counter() - start_time) * 1000
            )

            classification = classify_http_response(response)

            content_type = response.headers.get(
                "Content-Type",
                "unknown",
            )

            server = response.headers.get(
                "Server",
                "not disclosed",
            )

            final_url = response.url

            redirected = (
                final_url.rstrip("/")
                != url.rstrip("/")
            )

            return {
                "target": url,
                "final_url": final_url,
                "up": classification["up"],
                "code": response.status_code,
                "latency": latency,
                "health": latency_health(latency),
                "category": classification["category"],
                "cause": classification["cause"],
                "recommendation": classification["recommendation"],
                "content_type": content_type,
                "server": server,
                "redirected": redirected,
                "checked_at": time.time(),
            }

        except requests.exceptions.SSLError:
            return self.failure_result(
                target=url,
                category="SSL",
                cause=(
                    "The SSL certificate could not be verified, "
                    "may be expired, or may be misconfigured"
                ),
                recommendation=(
                    "Check the certificate expiration date, hostname coverage, "
                    "certificate chain, and TLS configuration."
                ),
            )

        except requests.exceptions.ConnectTimeout:
            return self.failure_result(
                target=url,
                category="connection timeout",
                cause=(
                    "The connection attempt timed out before reaching the server"
                ),
                recommendation=(
                    "Check firewall rules, routing, server availability, "
                    "load balancer health, and the destination port."
                ),
            )

        except requests.exceptions.ReadTimeout:
            return self.failure_result(
                target=url,
                category="read timeout",
                cause=(
                    "The server accepted the connection "
                    "but did not respond in time"
                ),
                recommendation=(
                    "Check application processing time, database queries, "
                    "upstream dependencies, and server load."
                ),
            )

        except requests.exceptions.TooManyRedirects:
            return self.failure_result(
                target=url,
                category="redirect",
                cause="The website entered a redirect loop",
                recommendation=(
                    "Review HTTP to HTTPS rules, reverse-proxy settings, "
                    "and application redirect configuration."
                ),
            )

        except requests.exceptions.ConnectionError as error:
            error_text = str(error).lower()

            if any(
                signature in error_text
                for signature in DNS_ERROR_SIGNATURES
            ):
                return self.failure_result(
                    target=url,
                    category="DNS",
                    cause=(
                        "DNS resolution failed because "
                        "the hostname could not be resolved"
                    ),
                    recommendation=(
                        "Verify the domain spelling, DNS records, "
                        "nameservers, and recent DNS changes."
                    ),
                )

            if "connection refused" in error_text:
                return self.failure_result(
                    target=url,
                    category="connection refused",
                    cause=(
                        "The host was reached but refused the connection"
                    ),
                    recommendation=(
                        "Check whether the service is running, "
                        "whether the correct port is exposed, "
                        "and whether firewall rules allow the connection."
                    ),
                )

            return self.failure_result(
                target=url,
                category="connection",
                cause=(
                    "A network connection to the server "
                    "could not be established"
                ),
                recommendation=(
                    "Check server availability, firewall rules, routing, "
                    "proxy settings, and network connectivity."
                ),
            )

        except requests.exceptions.RequestException as error:
            self.log_error(
                "HTTP request failed: " + repr(error)
            )

            return self.failure_result(
                target=url,
                category="request",
                cause=(
                    "The HTTP request failed before "
                    "a valid response was received"
                ),
                recommendation=(
                    "Check the URL, network connection, "
                    "proxy configuration, and server availability."
                ),
            )

        except Exception as error:
            self.log_error(
                "Unexpected diagnostic error: " + repr(error)
            )

            return self.failure_result(
                target=url,
                category="unexpected",
                cause="An unexpected diagnostic error occurred",
                recommendation=(
                    "Review the Buddy logs and retry the health check."
                ),
            )

    # --------------------------------------------------------
    # STATUS DURATION TRACKING
    # --------------------------------------------------------

    def track_duration(self, target, is_up):
        normalized_target = normalize_url(target)

        if not normalized_target:
            normalized_target = target.strip().lower()

        key = stable_target_key(normalized_target)
        current_time = time.time()
        current_state = "up" if is_up else "down"

        try:
            existing = self.capability_worker.get_single_key(key)
        except Exception as error:
            self.log_warning(
                "Could not read state: " + repr(error)
            )
            existing = None

        if not isinstance(existing, dict):
            existing = None

        if (
            not existing
            or "state" not in existing
            or "since" not in existing
        ):
            new_state = {
                "target": normalized_target,
                "state": current_state,
                "since": current_time,
                "last_checked": current_time,
                "checks": 1,
            }

            try:
                if existing:
                    self.capability_worker.update_key(
                        key,
                        new_state,
                    )
                else:
                    self.capability_worker.create_key(
                        key,
                        new_state,
                    )
            except Exception as error:
                self.log_warning(
                    "Could not create state: " + repr(error)
                )

            return {
                "text": "since the first Buddy check",
                "changed": False,
                "checks": 1,
            }

        previous_state = existing.get("state")

        try:
            previous_since = float(existing.get("since"))
        except Exception:
            previous_since = current_time

        try:
            checks = int(existing.get("checks", 0)) + 1
        except Exception:
            checks = 1

        if previous_state != current_state:
            updated_state = {
                "target": normalized_target,
                "state": current_state,
                "since": current_time,
                "last_checked": current_time,
                "checks": checks,
            }

            try:
                self.capability_worker.update_key(
                    key,
                    updated_state,
                )
            except Exception as error:
                self.log_warning(
                    "Could not update changed state: "
                    + repr(error)
                )

            return {
                "text": "just now",
                "changed": True,
                "previous_state": previous_state,
                "checks": checks,
            }

        elapsed_seconds = max(
            0,
            int(current_time - previous_since),
        )

        updated_state = dict(existing)
        updated_state["last_checked"] = current_time
        updated_state["checks"] = checks

        try:
            self.capability_worker.update_key(
                key,
                updated_state,
            )
        except Exception as error:
            self.log_warning(
                "Could not update check time: " + repr(error)
            )

        return {
            "text": self.format_duration(elapsed_seconds),
            "changed": False,
            "checks": checks,
        }

    def format_duration(self, seconds):
        if seconds < 5:
            return "a few seconds"

        if seconds < 60:
            return str(seconds) + " seconds"

        minutes = seconds // 60

        if minutes < 60:
            if minutes == 1:
                return "1 minute"

            return str(minutes) + " minutes"

        hours = minutes // 60
        remaining_minutes = minutes % 60

        if hours < 24:
            if hours == 1:
                hour_text = "1 hour"
            else:
                hour_text = str(hours) + " hours"

            if remaining_minutes:
                if remaining_minutes == 1:
                    minute_text = "1 minute"
                else:
                    minute_text = (
                        str(remaining_minutes) + " minutes"
                    )

                return hour_text + " and " + minute_text

            return hour_text

        days = hours // 24
        remaining_hours = hours % 24

        if days == 1:
            day_text = "1 day"
        else:
            day_text = str(days) + " days"

        if remaining_hours:
            if remaining_hours == 1:
                hour_text = "1 hour"
            else:
                hour_text = str(remaining_hours) + " hours"

            return day_text + " and " + hour_text

        return day_text

    # --------------------------------------------------------
    # RESPONSE GENERATION
    # --------------------------------------------------------

    def build_diagnostic_summary(
        self,
        result,
        duration,
    ):
        target = result.get("target") or "the target"
        code = result.get("code")
        latency = result.get("latency")
        health = result.get("health", "unknown")
        category = result.get("category", "unknown")
        cause = result.get("cause")
        recommendation = result.get("recommendation")
        final_url = result.get("final_url")
        redirected = result.get("redirected", False)

        duration_text = duration.get(
            "text",
            "an unknown duration",
        )

        if result.get("up"):
            parts = [
                "Target: " + str(target) + ".",
                "Status: UP.",
                "HTTP status: " + str(code) + ".",
                (
                    "Response time: "
                    + str(latency)
                    + " milliseconds."
                ),
                "Performance health: " + str(health) + ".",
                (
                    "Sentinel has observed this state for "
                    + str(duration_text)
                    + "."
                ),
            ]

            if category == "redirect":
                parts.append(
                    "The target is responding through an HTTP redirect."
                )

            if redirected and final_url:
                parts.append(
                    "Final destination: "
                    + str(final_url)
                    + "."
                )

            if duration.get("changed"):
                parts.append(
                    "The service has just recovered "
                    "from its previous state."
                )

            return " ".join(parts)

        parts = [
            "Target: " + str(target) + ".",
            "Status: DOWN or unhealthy.",
        ]

        if code is not None:
            parts.append(
                "HTTP status: " + str(code) + "."
            )
        else:
            parts.append(
                "No HTTP response code was received."
            )

        if latency is not None:
            parts.append(
                "Response time before failure: "
                + str(latency)
                + " milliseconds."
            )

        parts.append(
            "Incident category: " + str(category) + "."
        )

        parts.append(
            "Likely cause based on observed evidence: "
            + str(cause)
            + "."
        )

        parts.append(
            "Buddy has observed this state for "
            + str(duration_text)
            + "."
        )

        if recommendation:
            parts.append(
                "Recommended next action: "
                + str(recommendation)
            )

        if duration.get("changed"):
            parts.append(
                "This is a newly detected outage "
                "or unhealthy state."
            )

        return " ".join(parts)

    def make_spoken_response(self, factual_summary):
        system_prompt = (
            "You are buddy, a calm and precise senior DevOps "
            "incident consultant. Convert the diagnostic data into "
            "three or four short spoken sentences. Start with the "
            "status. State the HTTP code and response time when "
            "available. Explain the likely failure category and one "
            "recommended action. Never invent logs, historical uptime, "
            "causes, metrics, headers, or technical evidence. "
            "Do not use markdown, headings, or bullet points."
        )

        try:
            response = (
                self.capability_worker.text_to_text_response(
                    factual_summary,
                    system_prompt=system_prompt,
                )
            )

            if isinstance(response, str) and response.strip():
                return response.strip()

        except Exception as error:
            self.log_warning(
                "Response formatting failed: " + repr(error)
            )

        return factual_summary

    # --------------------------------------------------------
    # MAIN CONVERSATION LOOP
    # --------------------------------------------------------

    async def run(self):
        cw = self.capability_worker

        self.log_info("Ability started")

        try:
            await cw.speak(INTRO_PROMPT)

            self.log_info("Entry prompt completed")

            while True:
                try:
                    user_input = await cw.user_response()

                except Exception as error:
                    self.log_error(
                        "Listening failed: " + repr(error)
                    )

                    await cw.speak(
                        "I could not hear the request clearly. "
                        "Please say the website or API again."
                    )

                    continue

                if not isinstance(user_input, str):
                    continue

                user_input = user_input.strip()

                self.log_info(
                    "Received input: " + repr(user_input)
                )

                if not user_input:
                    await cw.speak(
                        "I did not catch a target. "
                        "Please say a website or API address."
                    )

                    continue

                if is_exit_request(user_input):
                    self.log_info("Exit command received")
                    break

                if is_help_request(user_input):
                    await cw.speak(HELP_PROMPT)
                    continue

                await cw.speak(
                    "Running the health and incident checks now."
                )

                try:
                    result = self.diagnose(user_input)

                    duration = self.track_duration(
                        result.get("target") or user_input,
                        bool(result.get("up")),
                    )

                    factual_summary = (
                        self.build_diagnostic_summary(
                            result,
                            duration,
                        )
                    )

                    self.log_info(
                        "Diagnostic result: "
                        + factual_summary
                    )

                    spoken_response = (
                        self.make_spoken_response(
                            factual_summary
                        )
                    )

                    await cw.speak(spoken_response)

                    await cw.speak(
                        "Give me another website or API, "
                        "or say stop to close buddy."
                    )

                except Exception as error:
                    self.log_error(
                        "Turn failed: " + repr(error)
                    )

                    await cw.speak(
                        "The diagnostic check encountered "
                        "an internal issue. Please try the "
                        "target again or provide another URL."
                    )

        except Exception as error:
            self.log_error(
                "Fatal ability error: " + repr(error)
            )

            try:
                await cw.speak(
                    "buddy encountered an unexpected "
                    "internal error and must close this session."
                )
            except Exception:
                pass

        finally:
            try:
                await cw.speak(EXIT_PROMPT)

            except Exception as error:
                self.log_error(
                    "Exit prompt failed: " + repr(error)
                )

            try:
                cw.resume_normal_flow()
                self.log_info(
                    "Normal OpenHome flow resumed"
                )

            except Exception as error:
                self.log_error(
                    "Could not resume normal flow: "
                    + repr(error)
                )