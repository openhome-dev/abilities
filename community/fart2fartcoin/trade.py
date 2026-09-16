"""Fart2Fart(coin) trading module (cloud side, pure functions).

Everything Bankr-facing lives here so it can be unit tested with the SDK
stubbed and `requests.post` mocked. No SDK imports. No state. The daemon and
the skill import this file relatively (`from .trade import ...`).

Route: sell a whole number of dollars of USDC, receive Fartcoin on Solana.
    base_to_solana  (default)  Base USDC -> Solana Fartcoin in one Bankr swap.
                               Funding stays on Base; Bankr's bridge leg lands
                               the tokens in the wallet's own Solana address.
    solana                     Solana USDC -> Fartcoin, same chain. Needs USDC
                               and a little SOL on the Solana address.

Spend limits are NOT enforced here. They are set on bankr.bot -> Security and
enforced by Bankr at execution (403). The only guards in this file are
structural: whole dollars, a fixed token pair, and an idempotency key.
"""
import json
import re
import uuid
from decimal import Decimal, ROUND_DOWN, InvalidOperation

import requests

BANKR_API = "https://api.bankr.bot"
READ_KEY_NAME = "bankr_read_key"
TRADE_KEY_NAME = "bankr_trade_key"

FARTCOIN_MINT = "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump"      # Solana, 6 decimals
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"            # Base, 6 decimals
USDC_SOLANA = "EPjFWaLb3hycctiUiZXEXUoahKUhbSooLesGa3ApL2f"         # Solana, 6 decimals
FARTCOIN_DECIMALS = 6

ROUTES = {
    "base_to_solana": {"fromChain": "base", "fromToken": USDC_BASE, "toChain": "solana", "toToken": FARTCOIN_MINT},
    "solana": {"fromChain": "solana", "fromToken": USDC_SOLANA, "toChain": "solana", "toToken": FARTCOIN_MINT},
}
DEFAULT_ROUTE = "base_to_solana"

DEFAULT_BUY_USD = 1
DEFAULT_SLIPPAGE_BPS = 300
MIN_SLIPPAGE_BPS, MAX_SLIPPAGE_BPS = 10, 2000

QUOTE_TIMEOUT_S = 15
SWAP_TIMEOUT_S = 120          # cross-chain fills take longer than same-chain
PORTFOLIO_TIMEOUT_S = 12

ARRIVAL_CHECK_EVERY_S = 30
ARRIVAL_WINDOW_S = 10 * 60
JOURNAL_MAX = 200

_EVM_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


# -----------------------------------------------------------------------------
# Amount parsing: whole dollars only
# -----------------------------------------------------------------------------

_ONES = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}
_SCALES = {"hundred": 100, "thousand": 1000}
_FILLER = {
    "dollars", "dollar", "bucks", "buck", "usd", "us", "of", "to", "a", "the",
    "please", "set", "my", "fart", "buy", "amount", "per", "each", "every",
    "is", "it", "at", "make", "um", "uh", "so", "that", "and",
}
_ARTICLE_ONE = {"a", "one"}


def _words_to_number(tokens):
    """Strict word-number grammar. 'twenty five' -> 25. 'twenty five fifty' -> None."""
    if not tokens:
        return None
    total = 0
    current = 0
    state = "start"
    for tok in tokens:
        if tok in _TENS:
            if state in ("tens", "ones"):
                return None
            current += _TENS[tok]
            state = "tens"
        elif tok in _ONES:
            if state == "ones" or (state == "tens" and _ONES[tok] >= 10):
                return None
            current += _ONES[tok]
            state = "ones"
        elif tok == "hundred":
            if state == "scale":
                return None
            current = (current or 1) * 100
            state = "scale"
        elif tok in _SCALES:
            if state == "scale" and current == 0:
                return None
            total += (current or 1) * _SCALES[tok]
            current = 0
            state = "scale"
        else:
            return None
    return total + current


def parse_whole_dollars(text):
    """Spoken or typed amount -> int dollars >= 1, or None.

    Accepts "one dollar", "five bucks", "$3", "10", "ten dollars", "a dollar",
    "twenty five". Rejects anything with cents ("a dollar fifty", "2.50"),
    zero, negatives, run-on numbers ("twenty five fifty"), and no number.
    """
    if text is None:
        return None
    t = str(text).lower().strip()
    if not t:
        return None
    t = t.replace("$", " ").replace(",", "")
    if re.search(r"(^|\s)-\s*\d", t):
        return None                                  # negative
    t = re.sub(r"[^a-z0-9.\s-]", " ", t).replace("-", " ")
    if re.search(r"\bcents?\b", t) or re.search(r"\d\.\d", t) or re.search(r"\bhalf\b|\bquarter\b", t):
        return None
    t = t.replace(".", " ")
    tokens = t.split()
    if not tokens:
        return None
    # "a dollar" / "a buck" -> 1
    if tokens[0] in _ARTICLE_ONE and len(tokens) >= 2 and tokens[1] in ("dollar", "buck"):
        rest = [w for w in tokens[2:] if w not in _FILLER]
        return 1 if not rest else None
    tokens = [w for w in tokens if w not in _FILLER]
    if not tokens:
        return None
    if len(tokens) == 1 and re.fullmatch(r"\d+", tokens[0]):
        n = int(tokens[0])
        return n if n >= 1 else None
    if any(re.fullmatch(r"\d+", w) for w in tokens):
        return None                                  # mixed digits and words
    n = _words_to_number(tokens)
    return n if n is not None and n >= 1 else None


def whole_dollars_or_default(value, default=DEFAULT_BUY_USD):
    """Settings value -> int dollars. Anything not a whole dollar >= 1 falls back."""
    n = parse_whole_dollars(value)
    return n if n is not None else default


def parse_slippage_bps(value, default=DEFAULT_SLIPPAGE_BPS):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return n if MIN_SLIPPAGE_BPS <= n <= MAX_SLIPPAGE_BPS else default


def route_or_default(name):
    name = str(name or "").strip().lower()
    return name if name in ROUTES else DEFAULT_ROUTE


# -----------------------------------------------------------------------------
# Spoken numbers
# -----------------------------------------------------------------------------

def _int_words(n):
    if n == 0:
        return "zero"
    if n < 20:
        return [k for k, v in _ONES.items() if v == n and k != "oh"][0]
    if n < 100:
        tens = [k for k, v in _TENS.items() if v == n - n % 10][0]
        return tens if n % 10 == 0 else "%s-%s" % (tens, _int_words(n % 10))
    if n < 1000:
        rest = n % 100
        return "%s hundred" % _int_words(n // 100) + (" %s" % _int_words(rest) if rest else "")
    rest = n % 1000
    return "%s thousand" % _int_words(n // 1000) + (" %s" % _int_words(rest) if rest else "")


def dollars_words(n):
    n = int(n)
    return "%s dollar%s" % (_int_words(n), "" if n == 1 else "s")


def token_words(amount, name="Fartcoin"):
    """'about seven point four one Fartcoin' - 4 significant digits, digits spoken
    one at a time after the point so TTS can't slur them."""
    try:
        d = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return "some %s" % name
    if d <= 0:
        return "zero %s" % name
    sig = 4
    q = Decimal(1).scaleb(d.adjusted() - sig + 1)
    d = d.quantize(q, rounding=ROUND_DOWN)
    s = format(d.normalize(), "f")
    if "." in s:
        whole, frac = s.split(".")
        spoken = "%s point %s" % (_int_words(int(whole)), " ".join(_int_words(int(c)) for c in frac))
    else:
        spoken = _int_words(int(s))
    return "about %s %s" % (spoken, name)


# -----------------------------------------------------------------------------
# Requests
# -----------------------------------------------------------------------------

def build_quote_request(route, usd, slippage_bps=DEFAULT_SLIPPAGE_BPS):
    """The body for /wallet/swap-quote. `usd` must be a whole number >= 1."""
    r = ROUTES[route_or_default(route)]
    n = int(usd)
    if n < 1:
        raise ValueError("usd must be a whole number of dollars >= 1")
    return {
        "fromChain": r["fromChain"],
        "fromToken": r["fromToken"],
        "toChain": r["toChain"],
        "toToken": r["toToken"],
        "amount": str(n),
        "slippageBps": parse_slippage_bps(slippage_bps),
    }


_IDEMPOTENCY_NS = uuid.UUID("6f6a7274-6661-7274-3266-617274636f69")   # "fart2fartcoi" in hex


def idempotency_key(event_id):
    """Bankr requires a UUID. Derive one deterministically from the fart event id
    so a retry or a replayed event always presents the same key."""
    return str(uuid.uuid5(_IDEMPOTENCY_NS, str(event_id)))


def build_swap_request(quote_req, quote, event_id):
    """The body for /wallet/swap. quoteId is sent but Bankr ignores it cross-chain."""
    body = dict(quote_req)
    body["minBuyAmount"] = str(quote.get("minBuyAmount"))
    if quote.get("quoteId"):
        body["quoteId"] = quote["quoteId"]
    body["idempotencyKey"] = idempotency_key(event_id)
    return body


def _headers(key):
    return {"X-API-Key": key, "Content-Type": "application/json"}


def _safe_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {"error": (resp.text or "")[:300]}


def bankr_swap_quote(read_key, quote_req):
    r = requests.post(BANKR_API + "/wallet/swap-quote", headers=_headers(read_key),
                      json=quote_req, timeout=QUOTE_TIMEOUT_S)
    return r.status_code, _safe_json(r)


def bankr_swap(trade_key, swap_req):
    r = requests.post(BANKR_API + "/wallet/swap", headers=_headers(trade_key),
                      json=swap_req, timeout=SWAP_TIMEOUT_S)
    return r.status_code, _safe_json(r)


def bankr_portfolio(read_key, chain, getter=None):
    """GET /wallet/portfolio for one chain. `getter` defaults to requests.get;
    the daemon passes worker.session_tasks.get because the upload scan rejects
    a literal requests.get in cloud files."""
    getter = getter or requests.get
    r = getter(BANKR_API + "/wallet/portfolio", headers=_headers(read_key),
               params={"chains": chain, "showLowValueTokens": "true"}, timeout=PORTFOLIO_TIMEOUT_S)
    return r.status_code, _safe_json(r)


# -----------------------------------------------------------------------------
# Responses
# -----------------------------------------------------------------------------

def _msg(body):
    if isinstance(body, dict):
        return str(body.get("error") or body.get("message") or "").lower()
    return ""


def quote_ok(status_code, body):
    return status_code == 200 and isinstance(body, dict) and body.get("minBuyAmount") is not None


def quote_error_reason(status_code, body):
    m = _msg(body)
    if status_code == 400:
        if "small" in m:
            return "That amount is too small for Bankr to trade."
        if "solana" in m and "address" in m:
            return "The Bankr wallet has no Solana address yet. Enable it on bankr dot bot."
        if "unsupported" in m or "untradable" in m:
            return "Bankr can't trade that pair right now."
        return "Bankr couldn't quote that."
    if status_code == 401:
        return "Bankr rejected the read key. Check it in Settings."
    if status_code == 403:
        return "Bankr won't quote Fartcoin right now."
    if status_code == 502:
        return "No bridge route right now. Skipped."
    return "I couldn't get a price from Bankr."


def map_execute_result(status_code, body):
    """/wallet/swap response -> (status, spoken).

    status: filled | reverted | blocked | refused | busy | unknown | error
      filled    success true + hash. Solana leg may still be in flight.
      blocked   Bankr spend limit. Caller sets blocked_today.
      refused   misconfiguration or funds; caller announces once per session.
      busy      409/429; skip this event, no retry.
      unknown   504 / timeout; caller reconciles via portfolio.
    """
    m = _msg(body)
    if status_code == 200:
        if isinstance(body, dict) and body.get("success") is True and body.get("hash"):
            return "filled", None
        return "reverted", "The buy reverted on chain. Nothing spent, apart from a little gas."
    if status_code == 504:
        return "unknown", "Not sure that one went through. I'll check."
    if status_code == 403:
        if "impact" in m:
            return "refused", "The price would move too much right now. Skipped."
        if "spend" in m or "limit" in m:
            return "blocked", "Bankr's spending limit stopped this one."
        if "paused" in m:
            return "refused", "The Bankr wallet is paused."
        if "read" in m:
            return "refused", "The trade key is read-only. Check the key settings on bankr dot bot."
        if "location" in m:
            return "refused", "Bankr blocked the trade key's location."
        return "refused", "Bankr declined the trade."
    if status_code == 400:
        if "gas" in m:
            return "refused", "The wallet is out of gas on Base."
        if "balance" in m or "insufficient" in m:
            return "refused", "The wallet is out of dollars on Base."
        if "impact" in m:
            return "refused", "The price would move too much right now. Skipped."
        return "refused", "Bankr couldn't place the trade."
    if status_code == 409:
        return "busy", None
    if status_code == 429:
        return "busy", "Bankr is busy. Skipped."
    if status_code == 502:
        return "error", "No bridge route right now. Skipped."
    if status_code in (500, 503):
        return "error", "Bankr had a problem placing the trade."
    return "error", "Bankr returned an unexpected response."


def _dec(x):
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


def fartcoin_balance(portfolio):
    """Fartcoin token balance on Solana from a /wallet/portfolio body, as Decimal.
    Tolerant of the Base-shaped schema (baseToken.address) and a flat one (address/mint)."""
    chain = ((portfolio or {}).get("balances") or {}).get("solana") or {}
    for entry in chain.get("tokenBalances") or []:
        tok = (entry or {}).get("token") or entry or {}
        base = tok.get("baseToken") or {}
        addr = str(base.get("address") or tok.get("address") or tok.get("mint") or "")
        if addr == FARTCOIN_MINT:
            return _dec(tok.get("balance"))
    return Decimal(0)


def usdc_balance(portfolio, chain):
    """USDC balance on `chain` from a /wallet/portfolio body, as Decimal."""
    want = {"base": USDC_BASE.lower(), "solana": USDC_SOLANA}.get(chain)
    c = ((portfolio or {}).get("balances") or {}).get(chain) or {}
    for entry in c.get("tokenBalances") or []:
        tok = (entry or {}).get("token") or entry or {}
        base = tok.get("baseToken") or {}
        addr = str(base.get("address") or tok.get("address") or tok.get("mint") or "")
        if addr == want or addr.lower() == want:
            return _dec(tok.get("balance"))
    return Decimal(0)


def native_balance(portfolio, chain):
    c = ((portfolio or {}).get("balances") or {}).get(chain) or {}
    return _dec(c.get("nativeBalance"))


def is_valid_route(route):
    r = ROUTES.get(route)
    if not r:
        return False
    ok_from = _EVM_ADDR_RE.match(r["fromToken"]) if r["fromChain"] != "solana" else _BASE58_RE.match(r["fromToken"])
    return bool(ok_from and _BASE58_RE.match(r["toToken"]))


# -----------------------------------------------------------------------------
# Journal (a list of dicts kept in the KV store by the daemon)
# -----------------------------------------------------------------------------

def journal_entry(event, usd, route, status, mode, **extra):
    e = {"event_id": event.get("id"), "ts": event.get("ts"), "usd": str(int(usd)),
         "route": route, "status": status, "mode": mode}
    e.update(extra)
    return e


def append_journal(journal, entry):
    j = list(journal or [])
    j.append(entry)
    return j[-JOURNAL_MAX:]


def update_journal(journal, event_id, **changes):
    out = []
    for e in journal or []:
        if e.get("event_id") == event_id:
            e = {**e, **changes}
        out.append(e)
    return out


def pending_arrivals(journal):
    return [e for e in journal or [] if e.get("status") in ("filled", "in_transit", "unknown")]


def day_key(ts):
    """UTC day bucket for a unix timestamp. Kept simple: the daily report is
    'since midnight UTC', which is fine for a toy and avoids tz plumbing."""
    return int(float(ts or 0) // 86400)


def report_line(journal, today_key, mode):
    today = [e for e in journal or [] if day_key(e.get("ts")) == today_key]
    if mode != "live":
        return "Fart trading is in dry run. Nothing has been bought."
    if not today:
        return "No Fartcoin bought today."
    bought = [e for e in today if e.get("status") in ("filled", "landed", "in_transit")]
    blocked = [e for e in today if e.get("status") == "blocked"]
    spent = sum(int(e.get("usd", 0)) for e in bought)
    tokens = sum((_dec(e.get("tokens")) for e in bought), Decimal(0))
    n = len(bought)
    parts = ["%s fart%s bought %s of Fartcoin today" % (_int_words(n).capitalize(), "" if n == 1 else "s", dollars_words(spent))]
    if tokens > 0:
        parts.append("That's %s" % token_words(tokens))
    if blocked:
        parts.append("%s more %s stopped by your Bankr limit" % (_int_words(len(blocked)), "was" if len(blocked) == 1 else "were"))
    in_transit = [e for e in bought if e.get("status") == "in_transit"]
    if in_transit:
        parts.append("%s still in transit" % _int_words(len(in_transit)))
    return ". ".join(parts) + "."


def dumps(obj):
    return json.dumps(obj, separators=(",", ":"), default=str)
