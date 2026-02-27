import json
import re
import asyncio
import base64
import uuid
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
import requests

from src.agent.capability import MatchingCapability
from src.main import AgentWorker
from src.agent.capability_worker import CapabilityWorker

# =============================================================================
# PACKAGE TRACKER ABILITY — Direct Carrier API Version
# Tracks packages via UPS, FedEx, USPS, and DHL direct carrier APIs.
# No third-party aggregator. Configure only the carriers you have credentials for.
# =============================================================================

# ── FedEx ────────────────────────────────────────────────────────────────────
# Get credentials from https://developer.fedex.com → My Apps → Track API scope
FEDEX_API_KEY    = "l70d7a0844f44a4f25845a16e1183434bd"     # ← paste here
FEDEX_SECRET_KEY = "5057a0cda71a4ad1b16db11ad87c2258"  # ← paste here
FEDEX_USE_SANDBOX = True   # Set False for production (apis.fedex.com)

# ── UPS ──────────────────────────────────────────────────────────────────────
# Get credentials from https://developer.ups.com → Add App → Track product
UPS_CLIENT_ID     = "your_ups_client_id"
UPS_CLIENT_SECRET = "your_ups_client_secret"
UPS_USE_CIE = True         # Set False for production (onlinetools.ups.com)

# ── USPS ─────────────────────────────────────────────────────────────────────
# Register at https://registration.shippingapis.com/
USPS_USER_ID = "338OPENH22O13"
# USPS has no sandbox — the same endpoint handles all requests

# ── DHL ──────────────────────────────────────────────────────────────────────
# Get API key from https://developer.dhl.com → Shipment Tracking - Unified
DHL_API_KEY  = "your_dhl_api_key"
DHL_USE_TEST = True        # Set False for production

# ── Derived base URLs ─────────────────────────────────────────────────────────
FEDEX_BASE_URL = "https://apis-sandbox.fedex.com" if FEDEX_USE_SANDBOX else "https://apis.fedex.com"
UPS_BASE_URL   = "https://wwwcie.ups.com"          if UPS_USE_CIE       else "https://onlinetools.ups.com"
USPS_BASE_URL  = "https://secure.shippingapis.com"
DHL_BASE_URL   = "https://api.dhl.com"

PACKAGES_FILE        = "pkgtracker_packages.json"
MAX_PACKAGES         = 20
DELIVERED_CLEANUP_DAYS = 2

EXIT_WORDS = [
    "done", "exit", "stop", "quit", "bye", "goodbye",
    "nothing else", "all good", "nope", "no thanks", "i'm good",
    "no", "that's it", "that's all",
]
CANCEL_WORDS = ["never mind", "cancel", "forget it", "nevermind"]

# Normalized status tags (all lowercase) → voice descriptions
STATUS_DESCRIPTIONS = {
    "delivered":        "Your package was delivered.",
    "out_for_delivery": "Your package is out for delivery today.",
    "in_transit":       "Your package is in transit.",
    "exception":        "There's an issue with your package. Check the carrier website for details.",
    "returned":         "Your package is being returned to the sender.",
    "held":             "Your package is being held for pickup.",
    "cancelled":        "This shipment has been cancelled.",
    "label_created":    "A label was created but the carrier hasn't picked it up yet.",
    "pending":          "Tracking registered but no carrier scan yet.",
    "unknown":          "Status not available.",
}

CARRIER_DISPLAY = {
    "ups":    "UPS",
    "fedex":  "FedEx",
    "usps":   "USPS",
    "dhl":    "DHL",
    "amazon": "Amazon Logistics",
}

# ── LLM prompt templates ──────────────────────────────────────────────────────

INTENT_CLASSIFICATION_PROMPT = """Classify this user input for a package tracking ability. Return ONLY valid JSON.

The user may want to:
- "add" a new tracking number
- "status_all" check status of all packages
- "status_one" check status of a specific package (include the nickname they mentioned)
- "list" their tracked packages
- "remove" a package from tracking (include the nickname they mentioned)

If unsure, default to "status_all".

Return format: {"mode": "add|status_all|status_one|list|remove", "nickname": "optional nickname if mentioned"}

User input: {user_input}

Recent conversation context: {context}"""

TRACKING_NUMBER_EXTRACT_PROMPT = """The user is providing a package tracking number. They may have typed it, pasted it, or spoken it aloud.
Extract ONLY the alphanumeric tracking number. Remove any filler words, spaces, or descriptions.
Return ONLY the tracking number string, nothing else.

User input: {user_input}"""

STATUS_SUMMARY_PROMPT = """You are a concise package status assistant. Summarize the user's package tracking updates in 2-4 sentences for voice.
Prioritize: packages out for delivery today, packages with status changes, then everything else.
Use nicknames, not tracking numbers. Include expected delivery dates when available. Be brief.

Package data:
{package_data}"""

NICKNAME_MATCH_PROMPT = """The user is asking about a specific package. Match their request to one of these tracked packages.
Return ONLY the package ID that best matches. If no good match, return "none".

User said: {user_input}

Tracked packages:
{packages_list}

Return ONLY the package ID string, nothing else."""


class PackageTrackerCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    packages: list = None
    initial_request: str = None

    # OAuth token cache — persist across invocations of the same instance
    _fedex_token: str = None
    _fedex_token_expires: float = 0.0
    _ups_token: str = None
    _ups_token_expires: float = 0.0

    # {{register_capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.packages = []
        self.initial_request = ""

        try:
            val = worker.live_transcription
            if val and isinstance(val, str):
                self.initial_request = val.strip()
        except AttributeError:
            pass

        self.worker.session_tasks.create(self.run())

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT
    # ─────────────────────────────────────────────────────────────────────────

    async def run(self):
        try:
            if not self._check_api_keys():
                await self.capability_worker.speak(
                    "I need at least one carrier API key to track packages. "
                    "Please add your FedEx, UPS, USPS, or DHL credentials in the ability settings."
                )
                return

            await self._load_packages()
            await self._cleanup_delivered()

            if self.initial_request:
                intent = self._classify_trigger_intent(self._get_trigger_context())
                mode = intent.get("mode", "status_all")
                self.log_info(f"Package Tracker activated (live_transcription). Mode: {mode}")

            elif not self.packages:
                mode = "add"
                intent = {"mode": "add", "nickname": None}
                self.log_info("Package Tracker activated. No packages on file → add mode.")

            else:
                # Path 3: has packages, trigger phrase not captured by live_transcription.
                # Ask a direct yes/no question. "Are you adding a tracking number?"
                # maps well to the most common trigger ("track a package"). If yes →
                # add mode immediately. If no → check status. This avoids the user
                # having to figure out what to say after hearing a vague "Package tracker."
                response = await self.capability_worker.run_io_loop(
                    "Package tracker. Are you adding a new tracking number?"
                )
                if not response or self._is_exit(response):
                    return
                lower = response.lower().strip()
                # Fast-path: map natural "yes / add / track" signals to add mode
                # without needing LLM classification.
                ADD_SIGNALS = ["yes", "yeah", "yep", "yup", "add", "new", "track",
                               "number", "id", "sure", "ok", "okay"]
                if any(sig in lower for sig in ADD_SIGNALS):
                    mode = "add"
                    intent = {"mode": "add", "nickname": None}
                    self.log_info("Package Tracker activated (Path 3 yes). Mode: add")
                else:
                    # "no", "check", "status", or anything else → classify normally
                    self.initial_request = response
                    intent = self._classify_trigger_intent(self._get_trigger_context())
                    mode = intent.get("mode", "status_all")
                    self.log_info(f"Package Tracker activated (Path 3 no). Mode: {mode}")

            if mode == "add":
                await self._handle_add()
            elif mode == "status_all":
                await self._handle_status_all()
            elif mode == "status_one":
                await self._handle_status_one(intent.get("nickname"))
            elif mode == "list":
                await self._handle_list()
            elif mode == "remove":
                await self._handle_remove(intent.get("nickname"))
            else:
                await self._handle_status_all()

        except Exception as e:
            self.log_err(f"Package Tracker unhandled error: {e}")
            await self.capability_worker.speak(
                "Something went wrong with the package tracker. Please try again."
            )
        finally:
            self.capability_worker.resume_normal_flow()

    # ─────────────────────────────────────────────────────────────────────────
    # API KEY CHECKS
    # ─────────────────────────────────────────────────────────────────────────

    def _check_api_keys(self) -> bool:
        return any([
            self._carrier_configured("fedex"),
            self._carrier_configured("ups"),
            self._carrier_configured("usps"),
            self._carrier_configured("dhl"),
        ])

    def _carrier_configured(self, carrier: str) -> bool:
        if carrier == "fedex":
            return (FEDEX_API_KEY not in ("", "your_fedex_api_key") and
                    FEDEX_SECRET_KEY not in ("", "your_fedex_secret_key"))
        if carrier == "ups":
            return (UPS_CLIENT_ID not in ("", "your_ups_client_id") and
                    UPS_CLIENT_SECRET not in ("", "your_ups_client_secret"))
        if carrier == "usps":
            return USPS_USER_ID not in ("", "your_usps_user_id")
        if carrier == "dhl":
            return DHL_API_KEY not in ("", "your_dhl_api_key")
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # CARRIER AUTO-DETECTION (from tracking number format)
    # ─────────────────────────────────────────────────────────────────────────

    def _detect_carrier_from_number(self, tracking_number: str) -> str:
        """Best-effort detection from tracking number format.
        Returns: 'ups' | 'fedex' | 'usps' | 'dhl' | 'amazon' | 'unknown'."""
        t = tracking_number.upper().replace(" ", "").replace("-", "")

        if t.startswith("TBA"):                              return "amazon"  # Amazon Logistics
        if re.match(r"^1Z[A-Z0-9]{16}$", t):               return "ups"     # UPS 18-char
        if re.match(r"^(JJD|JVGL|GM|LX|RX|3S)", t):        return "dhl"     # DHL Express prefixes
        if re.match(r"^\d{10}$", t):                         return "dhl"     # DHL Express 10-digit
        if re.match(r"^9[2-6]\d{18,}$", t):                 return "usps"    # USPS 20+ digit
        if re.match(r"^[A-Z]{2}\d{9}US$", t):               return "usps"    # USPS international
        if t.isdigit() and len(t) in (12, 15, 20):          return "fedex"   # FedEx numeric
        if re.match(r"^96\d{20}$", t):                      return "fedex"   # FedEx Ground 96-prefix
        return "unknown"

    def _parse_carrier_from_text(self, text: str) -> str:
        """Parse carrier name from user speech. Returns carrier key or None."""
        lower = text.lower()
        if "ups" in lower:
            return "ups"
        if "fedex" in lower or "fed ex" in lower:
            return "fedex"
        if "usps" in lower or "postal" in lower or "post office" in lower:
            return "usps"
        if "dhl" in lower:
            return "dhl"
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # FEDEX API
    # ─────────────────────────────────────────────────────────────────────────

    def _get_fedex_token(self) -> str:
        """Return a cached or freshly-obtained FedEx OAuth token."""
        now = time.time()
        if self._fedex_token and now < self._fedex_token_expires - 60:
            return self._fedex_token
        try:
            resp = requests.post(
                f"{FEDEX_BASE_URL}/oauth/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "client_credentials",
                    "client_id": FEDEX_API_KEY,
                    "client_secret": FEDEX_SECRET_KEY,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._fedex_token = data.get("access_token")
                self._fedex_token_expires = now + int(data.get("expires_in", 3600))
                return self._fedex_token
            self.log_err(f"FedEx token error: {resp.status_code} {resp.text[:200]}")
            return None
        except Exception as e:
            self.log_err(f"FedEx token exception: {e}")
            return None

    def _track_fedex(self, tracking_number: str) -> dict:
        """Track a FedEx package. Returns normalized status dict or {'error': ...}."""
        try:
            token = self._get_fedex_token()
            if not token:
                return {"error": "FedEx authentication failed. Check your API key and secret."}

            resp = requests.post(
                f"{FEDEX_BASE_URL}/track/v1/trackingnumbers",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "X-locale": "en_US",
                },
                json={
                    "trackingInfo": [
                        {"trackingNumberInfo": {"trackingNumber": tracking_number}}
                    ],
                    "includeDetailedScans": True,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                self.log_err(f"FedEx track error: {resp.status_code} {resp.text[:300]}")
                return {"error": f"FedEx returned HTTP {resp.status_code}"}

            data = resp.json()
            complete = data.get("output", {}).get("completeTrackResults", [])
            if not complete:
                return {"error": "No FedEx tracking results returned"}

            result = complete[0].get("trackResults", [{}])[0]

            # Check for errors embedded in the result
            errors = result.get("error", {})
            if errors:
                err_msg = errors.get("message", "Tracking not found")
                self.log_err(f"FedEx track result error: {err_msg}")
                return {"error": err_msg}

            latest = result.get("latestStatusDetail", {})
            status_code = latest.get("code", "")
            status_desc = latest.get("description", "")

            scan_events = result.get("scanEvents", [])
            location = ""
            if scan_events:
                loc = scan_events[0].get("scanLocation", {})
                city = loc.get("city", "")
                state = loc.get("stateOrProvinceCode", "")
                location = f"{city}, {state}".strip(", ")

            expected_delivery = (
                result.get("estimatedDeliveryTimeWindow", {})
                      .get("window", {})
                      .get("ends", "")
                or result.get("standardTransitTimeWindow", {})
                         .get("window", {})
                         .get("ends", "")
            )

            return {
                "carrier": "fedex",
                "tracking_number": tracking_number,
                "status": self._normalize_fedex_status(status_code, status_desc),
                "status_detail": status_desc,
                "location": location,
                "timestamp": scan_events[0].get("date", "") if scan_events else "",
                "expected_delivery": expected_delivery,
            }
        except Exception as e:
            self.log_err(f"FedEx track exception: {e}")
            return {"error": str(e)}

    def _normalize_fedex_status(self, code: str, desc: str) -> str:
        c, d = code.upper(), desc.upper()
        if c == "DL" or "DELIVERED" in d:                                  return "delivered"
        if c == "OD" or "OUT FOR DELIVERY" in d:                           return "out_for_delivery"
        if c in ("IT", "AR", "DP", "AF", "OC") or "IN TRANSIT" in d \
                or "ARRIVED" in d or "DEPARTED" in d:                      return "in_transit"
        if c == "DE" or "EXCEPTION" in d or "DELAY" in d:                  return "exception"
        if c == "HL" or "HOLD" in d:                                       return "held"
        if c == "RS" or "RETURN" in d:                                     return "returned"
        if c == "CA" or "CANCEL" in d:                                     return "cancelled"
        if c in ("PU", "PX") or "PICKED UP" in d or "LABEL" in d:         return "label_created"
        return "in_transit"

    # ─────────────────────────────────────────────────────────────────────────
    # UPS API
    # ─────────────────────────────────────────────────────────────────────────

    def _get_ups_token(self) -> str:
        """Return a cached or freshly-obtained UPS OAuth token."""
        now = time.time()
        if self._ups_token and now < self._ups_token_expires - 60:
            return self._ups_token
        try:
            credentials = base64.b64encode(
                f"{UPS_CLIENT_ID}:{UPS_CLIENT_SECRET}".encode()
            ).decode()
            resp = requests.post(
                f"{UPS_BASE_URL}/security/v1/oauth/token",
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self._ups_token = data.get("access_token")
                self._ups_token_expires = now + int(data.get("expires_in", 14400))
                return self._ups_token
            self.log_err(f"UPS token error: {resp.status_code} {resp.text[:200]}")
            return None
        except Exception as e:
            self.log_err(f"UPS token exception: {e}")
            return None

    def _track_ups(self, tracking_number: str) -> dict:
        """Track a UPS package. Returns normalized status dict or {'error': ...}."""
        try:
            token = self._get_ups_token()
            if not token:
                return {"error": "UPS authentication failed. Check your client ID and secret."}

            resp = requests.get(
                f"{UPS_BASE_URL}/api/track/v1/details/{tracking_number}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "transId": str(uuid.uuid4()),
                    "transactionSrc": "PackageTracker",
                },
                params={"locale": "en_US", "returnSignature": "false"},
                timeout=15,
            )
            if resp.status_code != 200:
                self.log_err(f"UPS track error: {resp.status_code} {resp.text[:300]}")
                return {"error": f"UPS returned HTTP {resp.status_code}"}

            data = resp.json()
            shipments = data.get("trackResponse", {}).get("shipment", [])
            if not shipments:
                return {"error": "No UPS shipment found for that tracking number"}

            package = shipments[0].get("package", [{}])[0]
            activity = package.get("activity", [])

            status_type = ""
            status_desc = ""
            location = ""
            timestamp = ""

            if activity:
                latest = activity[0]
                status_obj = latest.get("status", {})
                status_type = status_obj.get("type", "")
                status_desc = status_obj.get("description", "")
                loc = latest.get("location", {}).get("address", {})
                city = loc.get("city", "")
                state = loc.get("stateProvince", "")
                location = f"{city}, {state}".strip(", ")
                timestamp = f"{latest.get('date', '')} {latest.get('time', '')}".strip()

            # Delivery date: find entry with type "DEL"
            delivery_date = ""
            for dd in package.get("deliveryDate", []):
                if dd.get("type") == "DEL":
                    delivery_date = dd.get("date", "")
                    break
            if not delivery_date and package.get("deliveryDate"):
                delivery_date = package["deliveryDate"][0].get("date", "")

            return {
                "carrier": "ups",
                "tracking_number": tracking_number,
                "status": self._normalize_ups_status(status_type, status_desc),
                "status_detail": status_desc,
                "location": location,
                "timestamp": timestamp,
                "expected_delivery": delivery_date,
            }
        except Exception as e:
            self.log_err(f"UPS track exception: {e}")
            return {"error": str(e)}

    def _normalize_ups_status(self, type_: str, desc: str) -> str:
        t, d = type_.upper(), desc.upper()
        if t == "D" or "DELIVERED" in d:                     return "delivered"
        if t == "O" or "OUT FOR DELIVERY" in d:              return "out_for_delivery"
        if t == "X" or "EXCEPTION" in d or "DELAY" in d:    return "exception"
        if t == "M" or "LABEL CREATED" in d:                 return "label_created"
        if "RETURNED" in d:                                   return "returned"
        return "in_transit"  # covers I, P, and any other in-motion type

    # ─────────────────────────────────────────────────────────────────────────
    # USPS API
    # ─────────────────────────────────────────────────────────────────────────

    def _track_usps(self, tracking_number: str) -> dict:
        """Track a USPS package via the Web Tools XML API."""
        try:
            xml_body = (
                f'<TrackRequest USERID="{USPS_USER_ID}">'
                f'<TrackID ID="{tracking_number}"></TrackID>'
                f'</TrackRequest>'
            )
            resp = requests.get(
                f"{USPS_BASE_URL}/ShippingAPI.dll",
                params={"API": "TrackV2", "XML": xml_body},
                timeout=15,
            )
            if resp.status_code != 200:
                self.log_err(f"USPS track error: {resp.status_code}")
                return {"error": f"USPS returned HTTP {resp.status_code}"}

            root = ET.fromstring(resp.text)

            error_node = root.find(".//Error")
            if error_node is not None:
                err_desc = error_node.findtext("Description", "Unknown USPS error")
                self.log_err(f"USPS error: {err_desc}")
                return {"error": err_desc}

            summary = root.find(".//TrackSummary")
            if summary is None:
                return {"error": "No USPS tracking summary in response"}

            event_time = summary.findtext("EventTime", "")
            event_date = summary.findtext("EventDate", "")
            status_desc = summary.findtext("Event", "")
            city = summary.findtext("EventCity", "")
            state = summary.findtext("EventState", "")
            location = f"{city}, {state}".strip(", ")
            expected_delivery = summary.findtext("ExpectedDeliveryDate", "")

            return {
                "carrier": "usps",
                "tracking_number": tracking_number,
                "status": self._normalize_usps_status(status_desc),
                "status_detail": status_desc,
                "location": location,
                "timestamp": f"{event_date} {event_time}".strip(),
                "expected_delivery": expected_delivery,
            }
        except ET.ParseError as e:
            self.log_err(f"USPS XML parse error: {e}")
            return {"error": "Invalid XML response from USPS"}
        except Exception as e:
            self.log_err(f"USPS track exception: {e}")
            return {"error": str(e)}

    def _normalize_usps_status(self, desc: str) -> str:
        d = desc.upper()
        if "DELIVERED" in d:                                        return "delivered"
        if "OUT FOR DELIVERY" in d:                                 return "out_for_delivery"
        if "IN TRANSIT" in d or "ARRIVED" in d or "DEPARTED" in d \
                or "PROCESSED" in d or "ACCEPTED" in d:            return "in_transit"
        if "HELD" in d or "HOLD" in d or "AVAILABLE FOR PICKUP" in d: return "held"
        if "RETURN" in d:                                           return "returned"
        if "ALERT" in d or "NOTICE" in d:                          return "exception"
        if "LABEL" in d or "ELECTRONIC" in d:                      return "label_created"
        return "in_transit"

    # ─────────────────────────────────────────────────────────────────────────
    # DHL API
    # ─────────────────────────────────────────────────────────────────────────

    def _track_dhl(self, tracking_number: str) -> dict:
        """Track a DHL package via the Unified Tracking API."""
        try:
            resp = requests.get(
                f"{DHL_BASE_URL}/track/shipments",
                headers={
                    "DHL-API-Key": DHL_API_KEY,
                    "Accept": "application/json",
                },
                params={"trackingNumber": tracking_number, "language": "en"},
                timeout=15,
            )
            if resp.status_code != 200:
                self.log_err(f"DHL track error: {resp.status_code} {resp.text[:300]}")
                return {"error": f"DHL returned HTTP {resp.status_code}"}

            data = resp.json()
            shipments = data.get("shipments", [])
            if not shipments:
                return {"error": "No DHL shipment found for that tracking number"}

            shipment = shipments[0]
            events = shipment.get("events", [])
            status_obj = shipment.get("status", {})
            status_code = status_obj.get("status", "")
            status_desc = status_obj.get("description", "")

            location = ""
            timestamp = ""
            if events:
                latest = events[0]
                loc = latest.get("location", {}).get("address", {})
                city = loc.get("addressLocality", "")
                country = loc.get("countryCode", "")
                location = f"{city}, {country}".strip(", ")
                timestamp = latest.get("timestamp", "")

            expected_delivery = shipment.get("estimatedTimeOfDelivery", "")

            return {
                "carrier": "dhl",
                "tracking_number": tracking_number,
                "status": self._normalize_dhl_status(status_code, status_desc),
                "status_detail": status_desc,
                "location": location,
                "timestamp": timestamp,
                "expected_delivery": expected_delivery,
            }
        except Exception as e:
            self.log_err(f"DHL track exception: {e}")
            return {"error": str(e)}

    def _normalize_dhl_status(self, code: str, desc: str) -> str:
        c, d = code.upper(), desc.upper()
        if c == "DELIVERED" or "DELIVERED" in d:                   return "delivered"
        if c in ("OUT-FOR-DELIVERY",) or "OUT FOR DELIVERY" in d:  return "out_for_delivery"
        if c in ("TRANSIT", "IN-TRANSIT", "PROCESSED") \
                or "TRANSIT" in d or "ARRIVED" in d:               return "in_transit"
        if "EXCEPTION" in d or "DELAY" in d or "DAMAGE" in d:      return "exception"
        if "RETURN" in d:                                           return "returned"
        if "HELD" in d or "HOLD" in d:                             return "held"
        if "LABEL" in d:                                           return "label_created"
        return "in_transit"

    # ─────────────────────────────────────────────────────────────────────────
    # UNIFIED TRACKING ROUTER
    # ─────────────────────────────────────────────────────────────────────────

    def _track_package(self, carrier: str, tracking_number: str) -> dict:
        """Route to the appropriate carrier API. Returns normalized dict or {'error': ...}."""
        if carrier == "ups":   return self._track_ups(tracking_number)
        if carrier == "fedex": return self._track_fedex(tracking_number)
        if carrier == "usps":  return self._track_usps(tracking_number)
        if carrier == "dhl":   return self._track_dhl(tracking_number)
        return {"error": f"Carrier '{carrier}' is not supported"}

    # ─────────────────────────────────────────────────────────────────────────
    # TRIGGER CONTEXT & INTENT CLASSIFICATION
    # ─────────────────────────────────────────────────────────────────────────

    def _get_trigger_context(self) -> str:
        try:
            history = self.worker.agent_memory.full_message_history
            recent = history[-5:] if len(history) > 5 else history
            parts = []
            for msg in recent:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                if content:
                    parts.append(f"{role}: {content}")
            return "\n".join(parts)
        except Exception:
            return ""

    def _classify_trigger_intent(self, context: str) -> dict:
        user_input = self.initial_request
        if not user_input:
            try:
                history = self.worker.agent_memory.full_message_history
                for msg in reversed(history):
                    if msg.get("role") == "user" and msg.get("content"):
                        user_input = msg["content"]
                        break
            except Exception:
                pass

        self.log_info(f"Classifying trigger intent from: '{user_input}'")
        lower = (user_input or "").lower()

        ADD_KEYWORDS = [
            "track a package", "track my package", "track this package",
            "track package", "add a tracking", "new tracking",
            "track my order", "track an order", "track order", "add tracking",
        ]
        STATUS_ALL_KEYWORDS = [
            "any packages", "package update", "package status",
            "what's shipping", "check my packages", "delivery update",
            "check on my package", "check my order",
        ]
        LIST_KEYWORDS = [
            "how many packages", "list my packages", "list packages",
            "what am i tracking",
        ]
        REMOVE_KEYWORDS = [
            "stop tracking", "remove package", "delete tracking", "remove tracking",
        ]

        for phrase in ADD_KEYWORDS:
            if phrase in lower:
                return {"mode": "add", "nickname": None}
        for phrase in LIST_KEYWORDS:
            if phrase in lower:
                return {"mode": "list", "nickname": None}
        for phrase in REMOVE_KEYWORDS:
            if phrase in lower:
                return {"mode": "remove", "nickname": None}
        for phrase in STATUS_ALL_KEYWORDS:
            if phrase in lower:
                return {"mode": "status_all", "nickname": None}

        m = re.search(r"where(?:'s| is) (?:my |the )?(.+)", lower)
        if m:
            return {"mode": "status_one", "nickname": m.group(1).strip()}

        prompt = self._build_prompt(
            INTENT_CLASSIFICATION_PROMPT,
            user_input=user_input or "",
            context=context,
        )
        raw = self.capability_worker.text_to_text_response(prompt)
        clean = raw.replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(clean)
            if isinstance(result, dict) and "mode" in result:
                return result
        except json.JSONDecodeError:
            self.log_err(f"Failed to parse intent JSON: {clean[:200]}")

        return {"mode": "status_all", "nickname": None}

    # ─────────────────────────────────────────────────────────────────────────
    # PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────────

    async def _load_packages(self):
        try:
            exists = await self.capability_worker.check_if_file_exists(PACKAGES_FILE, False)
            if exists:
                raw = await self.capability_worker.read_file(PACKAGES_FILE, False)
                data = json.loads(raw)
                self.packages = data.get("packages", [])
            else:
                self.packages = []
        except Exception as e:
            self.log_err(f"Error loading packages: {e}")
            self.packages = []

    async def _save_packages(self):
        try:
            data = {"packages": self.packages}
            await self.capability_worker.delete_file(PACKAGES_FILE, False)
            await self.capability_worker.write_file(
                PACKAGES_FILE, json.dumps(data, indent=2), False
            )
        except Exception as e:
            self.log_err(f"Error saving packages: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # AUTO-CLEANUP DELIVERED PACKAGES
    # ─────────────────────────────────────────────────────────────────────────

    async def _cleanup_delivered(self):
        now = datetime.now(timezone.utc)
        cleaned = []
        removed_count = 0
        for pkg in self.packages:
            if pkg.get("delivered_date"):
                try:
                    delivered_dt = datetime.fromisoformat(pkg["delivered_date"])
                    if delivered_dt.tzinfo is None:
                        delivered_dt = delivered_dt.replace(tzinfo=timezone.utc)
                    if now - delivered_dt > timedelta(days=DELIVERED_CLEANUP_DAYS):
                        removed_count += 1
                        continue
                except Exception:
                    pass
            cleaned.append(pkg)
        if removed_count > 0:
            self.packages = cleaned
            await self._save_packages()
            self.log_info(f"Auto-cleaned {removed_count} delivered packages")

    # ─────────────────────────────────────────────────────────────────────────
    # HANDLE: ADD TRACKING
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_add(self):
        active_count = len([p for p in self.packages if p.get("last_status") != "delivered"])
        if active_count >= MAX_PACKAGES:
            await self.capability_worker.speak(
                f"You're already tracking {MAX_PACKAGES} packages. "
                "Remove one before adding another."
            )
            return

        while True:
            tracking_number = await self._capture_tracking_number()
            if not tracking_number:
                return

            carrier = None

            # Step 1: auto-detect carrier from tracking number format
            configured_carriers = [c for c in ("fedex", "ups", "usps", "dhl") if self._carrier_configured(c)]
            configured_display = " and ".join(CARRIER_DISPLAY[c] for c in configured_carriers)

            detected = self._detect_carrier_from_number(tracking_number)
            self.log_info(f"Auto-detected carrier: '{detected}' for {tracking_number}")

            if detected == "amazon":
                await self.capability_worker.speak(
                    "This looks like an Amazon Logistics tracking number. "
                    "Amazon doesn't provide a public tracking API, "
                    "so I can't pull live status. "
                    "You can track it at amazon.com or in the Amazon app."
                )
                confirmed = await self.capability_worker.run_confirmation_loop(
                    "Want to track a different package instead?"
                )
                if confirmed:
                    continue
                return

            elif detected != "unknown" and detected not in configured_carriers:
                # Detected a carrier we don't have credentials for — fail fast
                display = CARRIER_DISPLAY.get(detected, detected.upper())
                await self.capability_worker.speak(
                    f"That looks like a {display} tracking number, "
                    f"but I'm not set up for {display} yet. "
                    f"I can currently track {configured_display}."
                )
                confirmed = await self.capability_worker.run_confirmation_loop(
                    "Want to try a different tracking number?"
                )
                if confirmed:
                    continue
                return

            elif detected != "unknown":
                # Detected + configured — ask user to confirm
                display = CARRIER_DISPLAY.get(detected, detected.upper())
                confirmed = await self.capability_worker.run_confirmation_loop(
                    f"This looks like a {display} tracking number. Is that right?"
                )
                if confirmed:
                    carrier = detected

            if not carrier:
                # Unknown carrier or user declined detection
                if len(configured_carriers) == 1:
                    # Only one carrier set up — offer it directly instead of asking
                    single_display = CARRIER_DISPLAY[configured_carriers[0]]
                    confirmed = await self.capability_worker.run_confirmation_loop(
                        f"I couldn't identify the carrier. "
                        f"The only one I'm set up for is {single_display}. "
                        f"Should I try tracking with {single_display}?"
                    )
                    if not confirmed:
                        return
                    carrier = configured_carriers[0]
                else:
                    # Multiple carriers configured — ask the user, listing only what's available
                    response = await self.capability_worker.run_io_loop(
                        f"Which carrier is this? I can track {configured_display}."
                    )
                    if not response or self._is_cancel(response):
                        return
                    carrier = self._parse_carrier_from_text(response)
                    if not carrier or not self._carrier_configured(carrier):
                        await self.capability_worker.speak(
                            f"I can currently track {configured_display}. "
                            "Please say one of those carrier names."
                        )
                        confirmed = await self.capability_worker.run_confirmation_loop(
                            "Want to try again with a different tracking number?"
                        )
                        if confirmed:
                            continue
                        return

            # Step 2: get nickname
            nickname = await self._capture_nickname()
            if not nickname:
                nickname = "My package"

            # Step 3: call carrier API to verify the number and get initial status
            display = CARRIER_DISPLAY.get(carrier, carrier.upper())
            await self.capability_worker.speak(f"Checking with {display} now.")
            result = await asyncio.to_thread(self._track_package, carrier, tracking_number)

            if "error" in result:
                self.log_err(f"Track on add failed: {result['error']}")
                await self.capability_worker.speak(
                    f"Sorry, {display} couldn't verify that tracking number. "
                    f"{result['error']}."
                )
                confirmed = await self.capability_worker.run_confirmation_loop(
                    "Want to try a different tracking number?"
                )
                if confirmed:
                    continue
                return

            # Step 4: save and confirm
            now_iso = datetime.now(timezone.utc).isoformat()
            pkg_id = f"pkg_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:20]}"
            new_package = {
                "id": pkg_id,
                "tracking_number": tracking_number,
                "carrier": carrier,
                "carrier_display": display,
                "nickname": nickname,
                "last_status": result.get("status", "pending"),
                "last_status_detail": result.get("status_detail", ""),
                "location": result.get("location", ""),
                "expected_delivery": result.get("expected_delivery", ""),
                "last_checked": now_iso,
                "added_date": now_iso,
                "delivered_date": now_iso if result.get("status") == "delivered" else None,
            }
            self.packages.append(new_package)
            await self._save_packages()

            status_spoken = STATUS_DESCRIPTIONS.get(result.get("status", "pending"), "Status pending.")
            delivery_info = ""
            if result.get("expected_delivery"):
                delivery_info = f" Expected delivery: {self._format_date_for_speech(result['expected_delivery'])}."

            await self.capability_worker.speak(
                f"Got it. I'm now tracking your {nickname} via {display}. "
                f"{status_spoken}{delivery_info}"
            )

            confirmed = await self.capability_worker.run_confirmation_loop(
                "Want to track another package?"
            )
            if not confirmed:
                return

    async def _capture_tracking_number(self) -> str:
        ask_prompts = [
            "Please say your tracking number now, or type it in the chat.",
            "I didn't catch that. Please say the tracking number again.",
            "One more try — say each digit clearly, or type the number.",
        ]
        for attempt in range(3):
            user_input = await self.capability_worker.run_io_loop(ask_prompts[attempt])

            if not user_input:
                if attempt == 2:
                    await self.capability_worker.speak(
                        "Couldn't get the tracking number. Let's try again later."
                    )
                    return None
                continue

            if self._is_cancel(user_input):
                await self.capability_worker.speak("Okay, cancelled.")
                return None

            extract_prompt = self._build_prompt(TRACKING_NUMBER_EXTRACT_PROMPT, user_input=user_input)
            cleaned = self.capability_worker.text_to_text_response(extract_prompt).strip()
            cleaned = cleaned.replace(" ", "").replace("-", "").replace("```", "").strip()

            if len(cleaned) < 6:
                if attempt == 2:
                    await self.capability_worker.speak(
                        "I'm having trouble with that number. Let's try again later."
                    )
                    return None
                continue

            spelled_out = self._spell_out_tracking(cleaned)
            confirmed = await self._confirm_tracking_number(spelled_out)
            if confirmed:
                return cleaned
            if attempt == 2:
                await self.capability_worker.speak(
                    "Still having trouble getting the right number. Let's try again later."
                )
                return None

        return None

    async def _confirm_tracking_number(self, spelled_out: str) -> bool:
        """Ask the user to confirm a tracking number. Unlike run_confirmation_loop,
        this does NOT loop forever waiting for exactly 'yes' or 'no'. Any response
        that isn't clearly affirmative is treated as 'no' — so users who say
        'wrong' / 'change that' / 'two zeros six eight seven' all get looped back
        to re-enter the number rather than getting stuck in an SDK loop."""
        YES_WORDS = [
            "yes", "yeah", "yep", "yup", "correct", "right",
            "that's it", "that's right", "sure", "ok", "okay", "confirmed",
        ]
        response = await self.capability_worker.run_io_loop(
            f"I got: {spelled_out}. Say yes to confirm, or no to enter it again."
        )
        if not response:
            return False
        lower = response.lower().strip()
        return any(w in lower for w in YES_WORDS)

    async def _capture_nickname(self) -> str:
        response = await self.capability_worker.run_io_loop(
            "What should I call this package? Like 'Amazon order' or 'birthday gift'."
        )
        if response and not self._is_cancel(response):
            clean_prompt = (
                f"The user wants to name their package. Extract a short nickname (2-4 words max) "
                f"from: '{response}'. Return ONLY the nickname, nothing else."
            )
            nickname = self.capability_worker.text_to_text_response(clean_prompt).strip().strip('"').strip("'")
            return nickname if nickname else "My package"
        return "My package"

    # ─────────────────────────────────────────────────────────────────────────
    # HANDLE: STATUS CHECK (ALL PACKAGES)
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_status_all(self):
        if not self.packages:
            await self.capability_worker.speak(
                "You're not tracking any packages right now. "
                "Say 'track a package' to add one."
            )
            return

        active = [
            p for p in self.packages
            if p.get("last_status") != "delivered" or self._recently_delivered(p)
        ]
        if not active:
            await self.capability_worker.speak(
                "No active packages. Say 'track a package' to add one."
            )
            return

        await self.capability_worker.speak("Let me check on your packages.")
        statuses = await self._fetch_all_statuses()
        now_iso = datetime.now(timezone.utc).isoformat()
        changes = []

        for pkg in self.packages:
            fresh = statuses.get(pkg["id"])
            if not fresh or "error" in fresh:
                continue
            new_status = fresh.get("status", pkg.get("last_status", "pending"))
            if new_status != pkg.get("last_status", ""):
                changes.append(pkg["nickname"])
            pkg["last_status"] = new_status
            pkg["last_status_detail"] = fresh.get("status_detail", "")
            pkg["location"] = fresh.get("location", "")
            pkg["expected_delivery"] = fresh.get("expected_delivery") or pkg.get("expected_delivery", "")
            pkg["last_checked"] = now_iso
            if new_status == "delivered" and not pkg.get("delivered_date"):
                pkg["delivered_date"] = now_iso

        await self._save_packages()

        package_data = []
        for pkg in active:
            package_data.append({
                "nickname": pkg.get("nickname"),
                "carrier": pkg.get("carrier_display"),
                "status": pkg.get("last_status"),
                "detail": pkg.get("last_status_detail"),
                "location": pkg.get("location"),
                "expected_delivery": pkg.get("expected_delivery"),
                "status_changed": pkg.get("nickname") in changes,
            })

        summary_prompt = self._build_prompt(
            STATUS_SUMMARY_PROMPT,
            package_data=json.dumps(package_data, indent=2),
        )
        summary = self.capability_worker.text_to_text_response(summary_prompt)
        await self.capability_worker.speak(summary)

        response = await self.capability_worker.run_io_loop("Want details on any of these?")
        if response and not self._is_exit(response):
            await self._handle_status_one(response)

    # ─────────────────────────────────────────────────────────────────────────
    # HANDLE: STATUS CHECK (SINGLE PACKAGE)
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_status_one(self, nickname_hint: str = None):
        if not self.packages:
            await self.capability_worker.speak(
                "You're not tracking any packages. Say 'track a package' to add one."
            )
            return

        pkg = self._find_package_by_nickname(nickname_hint)
        if not pkg:
            await self.capability_worker.speak(
                "I couldn't find that package. Here's what you're tracking."
            )
            await self._handle_list()
            return

        await self.capability_worker.speak(f"Checking on your {pkg['nickname']}.")
        fresh = await asyncio.to_thread(
            self._track_package,
            pkg.get("carrier", ""),
            pkg.get("tracking_number", ""),
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        if fresh and "error" not in fresh:
            new_status = fresh.get("status", pkg.get("last_status", "pending"))
            pkg["last_status"] = new_status
            pkg["last_status_detail"] = fresh.get("status_detail", "")
            pkg["location"] = fresh.get("location", "")
            pkg["expected_delivery"] = fresh.get("expected_delivery") or pkg.get("expected_delivery", "")
            pkg["last_checked"] = now_iso
            if new_status == "delivered" and not pkg.get("delivered_date"):
                pkg["delivered_date"] = now_iso
            await self._save_packages()

            status_spoken = STATUS_DESCRIPTIONS.get(new_status, "Status unknown.")
            detail_parts = [
                f"Your {pkg['nickname']} via {pkg.get('carrier_display', 'unknown carrier')}. {status_spoken}"
            ]
            if fresh.get("location"):
                detail_parts.append(f"Last scan: {fresh['location']}.")
            if fresh.get("expected_delivery"):
                detail_parts.append(
                    f"Expected delivery: {self._format_date_for_speech(fresh['expected_delivery'])}."
                )
            await self.capability_worker.speak(" ".join(detail_parts))
        else:
            err = (fresh.get("error", "No response") if fresh else "No response")
            self.log_err(f"Status one fetch failed: {err}")
            await self.capability_worker.speak(
                f"Couldn't get a fresh update for your {pkg['nickname']}. "
                f"Last known: {STATUS_DESCRIPTIONS.get(pkg.get('last_status', ''), 'Unknown')}."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # PARALLEL STATUS FETCH
    # ─────────────────────────────────────────────────────────────────────────

    async def _fetch_all_statuses(self) -> dict:
        results = {}
        active = [p for p in self.packages if p.get("last_status") != "delivered"]
        if not active:
            return results

        async def fetch_one(pkg):
            carrier = pkg.get("carrier", "")
            number = pkg.get("tracking_number", "")
            if carrier and number:
                data = await asyncio.to_thread(self._track_package, carrier, number)
                results[pkg["id"]] = data

        await asyncio.gather(*[fetch_one(p) for p in active], return_exceptions=True)
        return results

    # ─────────────────────────────────────────────────────────────────────────
    # HANDLE: LIST PACKAGES
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_list(self):
        if not self.packages:
            await self.capability_worker.speak(
                "You're not tracking any packages right now. "
                "Say 'track a package' to add one."
            )
            return

        active = [
            p for p in self.packages
            if p.get("last_status") != "delivered" or self._recently_delivered(p)
        ]
        count = len(active)
        if count == 0:
            await self.capability_worker.speak("No active packages right now.")
            return

        summary_parts = [f"You're tracking {count} package{'s' if count != 1 else ''}."]
        for pkg in active:
            status = STATUS_DESCRIPTIONS.get(pkg.get("last_status", ""), "Status unknown")
            short_status = status.split(".")[0]
            carrier_label = pkg.get("carrier_display", "unknown carrier")
            summary_parts.append(f"{pkg['nickname']} via {carrier_label}: {short_status}.")

        full_summary = " ".join(summary_parts)
        if len(full_summary) > 400:
            prompt = (
                f"Summarize these tracked packages in 3-4 short sentences for voice: "
                f"{json.dumps([{'nickname': p['nickname'], 'carrier': p.get('carrier_display'), 'status': p.get('last_status')} for p in active])}"
            )
            full_summary = self.capability_worker.text_to_text_response(prompt)

        await self.capability_worker.speak(full_summary)

    # ─────────────────────────────────────────────────────────────────────────
    # HANDLE: REMOVE TRACKING
    # ─────────────────────────────────────────────────────────────────────────

    async def _handle_remove(self, nickname_hint: str = None):
        if not self.packages:
            await self.capability_worker.speak("You're not tracking any packages.")
            return

        pkg = self._find_package_by_nickname(nickname_hint)
        if not pkg:
            await self.capability_worker.speak(
                "I couldn't find that package. Here's what you're tracking."
            )
            await self._handle_list()
            return

        confirmed = await self.capability_worker.run_confirmation_loop(
            f"Remove '{pkg['nickname']}' from tracking? Say yes to confirm."
        )
        if not confirmed:
            await self.capability_worker.speak("Okay, keeping it.")
            return

        self.packages = [p for p in self.packages if p["id"] != pkg["id"]]
        await self._save_packages()
        await self.capability_worker.speak(f"Done. Removed '{pkg['nickname']}' from tracking.")

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _find_package_by_nickname(self, hint: str) -> dict:
        if not hint or not self.packages:
            return None
        lower_hint = hint.lower().strip()
        for pkg in self.packages:
            if pkg.get("nickname", "").lower() == lower_hint:
                return pkg
        for pkg in self.packages:
            if lower_hint in pkg.get("nickname", "").lower():
                return pkg
        packages_list = "\n".join(
            [f"ID: {p['id']}, Nickname: {p['nickname']}" for p in self.packages]
        )
        prompt = self._build_prompt(
            NICKNAME_MATCH_PROMPT,
            user_input=hint,
            packages_list=packages_list,
        )
        matched_id = self.capability_worker.text_to_text_response(prompt).strip().strip('"').strip("'")
        for pkg in self.packages:
            if pkg["id"] == matched_id:
                return pkg
        return None

    def _build_prompt(self, template: str, **kwargs) -> str:
        """Safe prompt builder using plain string replacement (avoids KeyError on JSON in content)."""
        result = template
        for key, value in kwargs.items():
            result = result.replace("{" + key + "}", str(value))
        return result

    def _is_exit(self, text: str) -> bool:
        lower = text.lower().strip()
        return any(word in lower for word in EXIT_WORDS)

    def _is_cancel(self, text: str) -> bool:
        lower = text.lower().strip()
        return any(phrase in lower for phrase in CANCEL_WORDS)

    def _recently_delivered(self, pkg: dict) -> bool:
        if pkg.get("last_status") != "delivered" or not pkg.get("delivered_date"):
            return False
        try:
            delivered_dt = datetime.fromisoformat(pkg["delivered_date"])
            if delivered_dt.tzinfo is None:
                delivered_dt = delivered_dt.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - delivered_dt <= timedelta(days=DELIVERED_CLEANUP_DAYS)
        except Exception:
            return False

    def _spell_out_tracking(self, tracking_number: str) -> str:
        digit_words = {
            "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
            "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine",
        }
        parts = []
        for ch in tracking_number:
            parts.append(digit_words[ch] if ch.isdigit() else ch.upper())
        return ", ".join(parts)

    def _format_date_for_speech(self, date_str: str) -> str:
        if not date_str:
            return ""
        s = str(date_str).strip()
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
            try:
                dt = datetime.strptime(s[: len(fmt)], fmt)
                break
            except ValueError:
                continue
        if not dt:
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                return s  # return raw string as fallback
        now = datetime.now(timezone.utc)
        diff = (dt.date() - now.date()).days
        if diff == 0:   return "today"
        if diff == 1:   return "tomorrow"
        if diff == -1:  return "yesterday"
        if 2 <= diff <= 6: return dt.strftime("%A")
        return dt.strftime("%B %d")

    def log_info(self, msg: str):
        try:
            self.worker.editor_logging_handler.info(msg)
        except Exception:
            pass

    def log_err(self, msg: str):
        try:
            self.worker.editor_logging_handler.error(msg)
        except Exception:
            pass
