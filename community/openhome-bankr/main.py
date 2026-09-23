import asyncio
import json
import re
import time
import uuid
from decimal import Decimal, ROUND_DOWN, InvalidOperation

import requests

from src.agent.capability import MatchingCapability
from src.agent.capability_worker import CapabilityWorker
from src.main import AgentWorker

# =============================================================================
# OPENHOME BANKR
# Buy and sell Bitcoin / Ethereum by voice through the user's Bankr wallet.
#
# Voice carries intent, never authority. Every trade is quoted first, read back
# in dollars, and confirmed by the user repeating the dollar amount. Amounts are
# always in US dollars. BTC / ETH / USD resolve locally; any other token is
# looked up through Bankr's Agent API with the READ-ONLY key (it cannot spend)
# and executed through the Wallet API. Sells resolve against what the user
# holds. The ability can read the portfolio, read a price, swap inside the
# wallet, and lock itself for a while. It cannot add recipients, change limits,
# or send funds anywhere.
#
# Keys (Settings -> API Keys):
#   bankr_read_key   read-only key, Wallet API + Agent API on  (portfolio, prices, quotes, lookups)
#   bankr_trade_key  Wallet API key, read-only off             (swap execution) -- optional
# =============================================================================

BANKR_API = "https://api.bankr.bot"
COINGECKO_PRICE = "https://api.coingecko.com/api/v3/simple/price"
DEXSCREENER_SEARCH = "https://api.dexscreener.com/latest/dex/search"
COINGECKO_SEARCH = "https://api.coingecko.com/api/v3/search"
COINGECKO_COIN = "https://api.coingecko.com/api/v3/coins/"

READ_KEY_NAME = "bankr_read_key"
TRADE_KEY_NAME = "bankr_trade_key"

CHAIN = "base"

# Hard voice caps. Deliberately under Bankr's own wallet limits so the speaker
# refuses before Bankr does. Users who want more raise the cap on bankr.bot with
# a timer, not here.
VOICE_MAX_PER_TRADE_USD = Decimal("25")
VOICE_MAX_DAILY_USD = Decimal("100")
MIN_TRADE_USD = Decimal("1")
MIN_SELL_ALL_USD = Decimal("0.25")        # "sell all" of a dust position is refused

QUOTE_MAX_AGE_S = 45          # older than this -> re-quote before executing
PRICE_DRIFT_MAX = Decimal("0.03")         # menu tokens: quote vs CoinGecko
PRICE_DRIFT_MAX_OTHER = Decimal("0.08")   # resolved tokens: quote vs resolver price
MIN_MARKET_CAP_USD = Decimal("1000000")   # below this a token is refused by voice
MIN_LIQUIDITY_USD = Decimal("250000")     # thin pools are refused by voice
RESOLVE_TIMEOUT_S = 15                    # agent lookup ceiling
MATCH_RATIO = 0.8                         # fuzzy match floor for held tokens
DEFAULT_LOCK_S = 24 * 3600
MISMATCH_PAUSE_S = 15 * 60

READ_TIMEOUT = 12
EXECUTE_TIMEOUT = 90

# Spoken asset menu. Nothing outside this list is tradable by voice.
ASSETS = {
    "USD": {
        "name": "dollars",
        "symbol": "USDC",
        "address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "decimals": 6,
        "coingecko": "usd-coin",
        "aliases": ["usd", "dollars", "dollar", "cash", "usdc", "us dollars"],
    },
    "BTC": {
        "name": "Bitcoin",
        "symbol": "cbBTC",
        "address": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
        "decimals": 8,
        "coingecko": "bitcoin",
        "aliases": ["btc", "bitcoin", "bit coin", "cbbtc", "coinbase bitcoin"],
    },
    "ETH": {
        "name": "Ethereum",
        "symbol": "ETH",
        "address": "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
        "decimals": 18,
        "coingecko": "ethereum",
        "aliases": ["eth", "ethereum", "ether", "etherium", "ethereum coin"],
    },
}

# Key-value store keys. The store is shared with every other installed ability,
# so nothing sensitive goes here: only the lock timer and a rolling spend log.
KV_LOCK = "openhome_bankr_lock"
KV_SPEND = "openhome_bankr_spend"

INTENT_SYSTEM_PROMPT = """You extract a trading intent from one spoken sentence.
Reply with ONLY a JSON object, no prose, no code fences, with these keys:
  action: one of "buy", "sell", "price", "portfolio", "lock", "help", "cancel", "unknown"
  asset:  the coin exactly as the user named it, as a short string, or null  (e.g. "bitcoin", "degen", "pepe", "dollars")
  usd:    a number or null                      (dollar amount mentioned, if any)
  all:    true or false                         (true if the user said "all" / "everything")
  hours:  a number or null                      (only for lock: how long, if stated)
Rules: "buy fifty dollars of bitcoin" -> buy "bitcoin" usd 50. "sell all my ethereum" -> sell "ethereum" all true. "buy ten dollars of degen" -> buy "degen" usd 10.
"what's bitcoin at" / "bitcoin price" -> price BTC. "how's my portfolio" / "check my crypto" / "how much do I have" -> portfolio.
"open my wallet" with nothing else -> help. Never invent an amount that was not said."""


# -----------------------------------------------------------------------------
# Pure helpers (no SDK dependency; covered by tests/)
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
_SCALES = {"hundred": 100, "thousand": 1000, "million": 1_000_000}
_FILLER = {
    "dollars", "dollar", "bucks", "buck", "usd", "us", "of", "and", "a",
    "the", "please", "yes", "yeah", "yep", "confirm", "confirmed", "ok",
    "okay", "it's", "its", "that's", "thats", "right", "correct", "sure",
    "exactly", "amount", "is", "um", "uh", "it", "s", "that", "so", "make",
}


def _words_to_number(tokens):
    """Parse a list of number-words into an int. Returns None if it isn't one.

    Strict grammar so run-on numbers ("twenty five fifty", "fifteen sixteen")
    are rejected instead of silently summed: after a tens word only a single
    digit may follow; after a ones/teen word only a scale word may follow.
    """
    if not tokens:
        return None
    total = 0
    current = 0
    state = "start"          # start | tens | ones | scale
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


def normalize_usd(text):
    """Turn a spoken amount into a Decimal of dollars, or None if ambiguous.

    Accepts "fifty", "50", "$50", "fifty dollars", "fifty bucks", "12.50",
    "five zero" (digit-by-digit), "twenty five", "one hundred twenty".
    Rejects anything with two separate numbers ("twenty five fifty") or no
    number at all. Cents only via digits ("12.50") or "X dollars and Y cents".
    """
    if not text:
        return None
    t = text.lower().strip()
    t = t.replace("$", " ").replace(",", "")
    t = re.sub(r"[^a-z0-9.\s-]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)   # keep only decimal points between digits
    t = t.replace("-", " ")

    # "X dollars and Y cents"
    m = re.search(r"(.+?)\s+dollars?\s+and\s+(.+?)\s+cents?", t)
    if m:
        d = normalize_usd(m.group(1))
        c_tokens = [w for w in m.group(2).split() if w not in _FILLER]
        c = _words_to_number(c_tokens) if not m.group(2).strip().isdigit() else int(m.group(2))
        if d is None or c is None or c >= 100:
            return None
        return (d + Decimal(c) / 100).quantize(Decimal("0.01"))

    tokens = [w for w in t.split() if w not in _FILLER]
    if not tokens:
        return None

    # Pure digits, possibly with a decimal point: "50", "12.50"
    if len(tokens) == 1 and re.fullmatch(r"\d+(\.\d{1,2})?", tokens[0]):
        return Decimal(tokens[0]).quantize(Decimal("0.01"))

    # Digit-by-digit: "five zero", "1 2 0"
    if len(tokens) >= 2 and all(
        (w in _ONES and _ONES[w] < 10) or re.fullmatch(r"\d", w) for w in tokens
    ):
        digits = "".join(str(_ONES[w]) if w in _ONES else w for w in tokens)
        return Decimal(digits).quantize(Decimal("0.01"))

    # Word number: "fifty", "twenty five", "one hundred twenty"
    n = _words_to_number(tokens)
    if n is None:
        return None
    return Decimal(n).quantize(Decimal("0.01"))


def _int_words(n):
    if n == 0:
        return "zero"
    if n < 20:
        return [k for k, v in _ONES.items() if v == n and k != "oh"][0]
    if n < 100:
        tens = [k for k, v in _TENS.items() if v == n - n % 10][0]
        return tens if n % 10 == 0 else f"{tens}-{_int_words(n % 10)}"
    if n < 1000:
        rest = n % 100
        return f"{_int_words(n // 100)} hundred" + (f" {_int_words(rest)}" if rest else "")
    if n < 1_000_000:
        rest = n % 1000
        return f"{_int_words(n // 1000)} thousand" + (f" {_int_words(rest)}" if rest else "")
    rest = n % 1_000_000
    return f"{_int_words(n // 1_000_000)} million" + (f" {_int_words(rest)}" if rest else "")


def usd_words(amount, with_digits=False):
    """'fifty dollars' / 'twelve dollars and fifty cents'; digits repeated when
    asked or when the amount is >= 100 ('one hundred twenty dollars, one two zero')."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    dollars = int(amount)
    cents = int((amount - dollars) * 100)
    s = f"{_int_words(dollars)} dollar" + ("" if dollars == 1 else "s")
    if cents:
        s += f" and {_int_words(cents)} cent" + ("" if cents == 1 else "s")
    if with_digits or dollars >= 100 or cents:
        digits = " ".join(str(dollars))
        if cents:
            digits += " point " + " ".join(f"{cents:02d}")
        s += f", {digits}"
    return s


def asset_words(amount, name):
    """Speak a token amount to at most 5 significant digits, digit by digit
    after the decimal point so TTS can't slur it. `name` is the display name."""
    if name in ASSETS:
        name = ASSETS[name]["name"]
    d = Decimal(amount)
    if d == 0:
        return f"zero {name}"
    sig = 5
    exp = d.adjusted()
    q = Decimal(1).scaleb(exp - sig + 1)
    d = d.quantize(q, rounding=ROUND_DOWN)
    s = format(d.normalize(), "f")
    if "." in s:
        whole, frac = s.split(".")
        spoken = f"{_int_words(int(whole))} point " + " ".join(_int_words(int(c)) for c in frac)
    else:
        spoken = _int_words(int(s))
    return f"about {spoken} {name}"


def price_words(price):
    p = Decimal(price)
    if p >= 1000:
        return _int_words(int(p.quantize(Decimal("1")))) + " dollars"
    if p >= 1:
        return usd_words(p.quantize(Decimal("0.01")))
    cents = p * 100
    if cents >= 1:
        c = cents.quantize(Decimal("0.1"))
        return f"{format(c.normalize(), 'f')} cents"
    # Sub-cent: three significant digits, spoken digit by digit.
    sig = cents.quantize(Decimal(1).scaleb(cents.adjusted() - 2), rounding=ROUND_DOWN)
    digits = format(sig.normalize(), "f")
    return " ".join("point" if ch == "." else _int_words(int(ch)) for ch in digits) + " of a cent"


def about_usd_words(amount):
    """For approximate figures in read-backs: 'about one dollar', 'about ninety cents'."""
    d = Decimal(amount)
    if d < Decimal("0.995"):
        cents = int((d * 100).quantize(Decimal("1")))
        return f"about {_int_words(cents)} cent" + ("" if cents == 1 else "s")
    return "about " + rounded_usd_words(d)


def rounded_usd_words(amount):
    """For balances: nearest dollar, no cents, no digit repeat."""
    n = int(Decimal(amount).quantize(Decimal("1")))
    return f"{_int_words(n)} dollar" + ("" if n == 1 else "s")


def resolve_asset(text):
    if not text:
        return None
    t = str(text).strip().lower()
    if t.upper() in ASSETS:
        return t.upper()
    for key, a in ASSETS.items():
        if t in a["aliases"]:
            return key
    return None


def sanitize_asset_text(text):
    """Letters, digits and spaces only, max 40 chars. Never the raw utterance."""
    if not text:
        return ""
    t = re.sub(r"[^A-Za-z0-9 ]+", " ", str(text)).strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t[:40]


_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def parse_resolver_json(raw):
    """Candidates from the Bankr agent's lookup reply. Anything malformed is
    dropped; prose is never used. Returns a list (possibly empty)."""
    if not raw:
        return []
    m = re.search(r"\{.*\}", str(raw), re.S)
    if not m:
        return []
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out = []
    for c in (obj.get("candidates") if isinstance(obj, dict) else None) or []:
        if not isinstance(c, dict):
            continue
        addr = str(c.get("address") or "").strip()
        name = sanitize_asset_text(c.get("name"))
        symbol = re.sub(r"[^A-Za-z0-9]", "", str(c.get("symbol") or "")).upper()[:12]
        try:
            decimals = int(c.get("decimals"))
            price = Decimal(str(c.get("price_usd")))
            mcap = Decimal(str(c.get("market_cap_usd") or 0))
            conf = float(c.get("confidence") or 0)
            change = c.get("change_24h_pct")
            change = float(change) if change is not None else None
        except (TypeError, ValueError, InvalidOperation):
            continue
        if not _ADDR_RE.match(addr) or not name or not (0 <= decimals <= 18) or price <= 0:
            continue
        out.append({
            "name": name.title(), "symbol": symbol or name.upper()[:8], "address": addr,
            "decimals": decimals, "ref_price": price, "market_cap": mcap,
            "change_24h": change, "confidence": max(0.0, min(conf, 1.0)), "is_menu": False,
        })
    return out[:3]


def _name_confidence(query, name, symbol):
    q, n, sy = _norm(query), _norm(name), _norm(symbol)
    if not q:
        return 0.0
    if q == n or q == sy:
        return 1.0
    words = [_norm(w) for w in str(name or "").split()]
    if q in words or n.startswith(q):
        return 0.8
    if sy.startswith(q) or q.startswith(sy) and len(sy) >= 3:
        return 0.7
    if q in n:
        return 0.5
    return 0.2


def dexscreener_candidates(body, query):
    """Candidates from a DexScreener /latest/dex/search body: Base pairs only,
    one entry per token (its deepest pool), scored by name match then liquidity.
    Weak matches (< 0.5) are dropped so loose search hits don't become buys."""
    best = {}
    for pair in (body or {}).get("pairs") or []:
        if not isinstance(pair, dict) or pair.get("chainId") != CHAIN:
            continue
        tok = pair.get("baseToken") or {}
        addr = str(tok.get("address") or "").strip()
        if not _ADDR_RE.match(addr):
            continue
        try:
            liq = Decimal(str((pair.get("liquidity") or {}).get("usd") or 0))
            price = Decimal(str(pair.get("priceUsd") or 0))
            mcap = Decimal(str(pair.get("marketCap") or pair.get("fdv") or 0))
            h24 = (pair.get("priceChange") or {}).get("h24")
            h24 = float(h24) if h24 is not None else None
        except (InvalidOperation, TypeError, ValueError):
            continue
        if price <= 0:
            continue
        name = sanitize_asset_text(tok.get("name")).title()
        symbol = re.sub(r"[^A-Za-z0-9]", "", str(tok.get("symbol") or "")).upper()[:12]
        if not name:
            continue
        conf = _name_confidence(query, name, symbol)
        if conf < 0.5:
            continue
        key = addr.lower()
        if key in best and best[key]["liquidity"] >= liq:
            continue
        best[key] = {"name": name, "symbol": symbol or name.upper()[:8], "address": addr,
                     "decimals": None, "ref_price": price, "market_cap": mcap, "liquidity": liq,
                     "change_24h": h24, "confidence": conf, "is_menu": False}
    ranked = sorted(best.values(), key=lambda c: (c["confidence"], c["liquidity"]), reverse=True)
    return ranked[:3]


def coingecko_candidate(coin, query, order):
    """Candidate record from a CoinGecko /coins/{id} body, or None if the coin
    has no Base contract. Confidence: exact name/symbol match beats rank order."""
    try:
        addr = str(((coin.get("platforms") or {}).get("base")) or "").strip()
        if not _ADDR_RE.match(addr):
            return None
        name = sanitize_asset_text(coin.get("name"))
        symbol = re.sub(r"[^A-Za-z0-9]", "", str(coin.get("symbol") or "")).upper()[:12]
        dp = ((coin.get("detail_platforms") or {}).get("base") or {}).get("decimal_place")
        decimals = int(dp) if dp is not None else 18
        md = coin.get("market_data") or {}
        price = Decimal(str((md.get("current_price") or {}).get("usd")))
        mcap = Decimal(str((md.get("market_cap") or {}).get("usd") or 0))
        change = md.get("price_change_percentage_24h")
        change = float(change) if change is not None else None
    except (TypeError, ValueError, InvalidOperation, AttributeError):
        return None
    if not name or price <= 0 or not (0 <= decimals <= 18):
        return None
    q = _norm(query)
    exact = q and (q == _norm(name) or q == _norm(symbol))
    conf = 1.0 if exact else {0: 0.85, 1: 0.55, 2: 0.35}.get(order, 0.2)
    return {"name": name.title(), "symbol": symbol or name.upper()[:8], "address": addr,
            "decimals": decimals, "ref_price": price, "market_cap": mcap,
            "change_24h": change, "confidence": conf, "is_menu": False}


def pick_candidate(cands):
    """(status, payload): ('none', None) | ('small', cand) | ('ambiguous', [a, b]) | ('ok', cand)."""
    if not cands:
        return "none", None
    cands = sorted(cands, key=lambda c: c["confidence"], reverse=True)
    big = [c for c in cands
           if (c.get("market_cap") or 0) >= MIN_MARKET_CAP_USD
           and (c.get("liquidity") is None or c["liquidity"] >= MIN_LIQUIDITY_USD)]
    if not big:
        return "small", cands[0]
    if len(big) >= 2 and big[0]["confidence"] - big[1]["confidence"] < 0.2:
        return "ambiguous", big[:2]
    return "ok", big[0]


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def match_holding(asset_text, holdings):
    """(status, payload) against held tokens: ('none', None) | ('ambiguous', [a, b]) | ('ok', h).
    Exact symbol/name first, then fuzzy on name and symbol."""
    import difflib
    q = _norm(asset_text)
    if not q:
        return "none", None
    items = [h for h in holdings.values() if h.get("amount", 0) > 0]
    exact = [h for h in items if _norm(h.get("symbol")) == q or _norm(h.get("name")) == q]
    if len(exact) == 1:
        return "ok", exact[0]
    if len(exact) > 1:
        return "ambiguous", exact[:2]
    # First word of the name ("aerodrome" for "Aerodrome Finance").
    first = [h for h in items if _norm(str(h.get("name") or "").split(" ")[0]) == q and len(q) >= 3]
    if len(first) == 1:
        return "ok", first[0]
    if len(first) > 1:
        return "ambiguous", first[:2]
    scored = []
    for h in items:
        r = max(
            difflib.SequenceMatcher(None, q, _norm(h.get("name"))).ratio(),
            difflib.SequenceMatcher(None, q, _norm(h.get("symbol"))).ratio(),
        )
        if r >= MATCH_RATIO:
            scored.append((r, h))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return "none", None
    if len(scored) >= 2 and scored[0][0] - scored[1][0] < 0.1:
        return "ambiguous", [scored[0][1], scored[1][1]]
    return "ok", scored[0][1]


def menu_token(key):
    a = ASSETS[key]
    return {"name": a["name"], "symbol": a["symbol"], "address": a["address"],
            "decimals": a["decimals"], "ref_price": None, "market_cap": None,
            "change_24h": None, "confidence": 1.0, "is_menu": True, "key": key}


def parse_intent_json(raw):
    """Pull the JSON object out of an LLM reply. Never trusts anything else."""
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    action = str(obj.get("action", "unknown")).lower()
    if action not in {"buy", "sell", "price", "portfolio", "lock", "help", "cancel", "unknown"}:
        action = "unknown"
    usd = None
    if obj.get("usd") is not None:
        try:
            usd = Decimal(str(obj["usd"])).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            usd = None
    hours = None
    if obj.get("hours") is not None:
        try:
            hours = float(obj["hours"])
        except (TypeError, ValueError):
            hours = None
    asset_text = sanitize_asset_text(obj.get("asset"))
    return {
        "action": action,
        "asset": resolve_asset(asset_text),   # menu key (BTC/ETH/USD) or None
        "asset_text": asset_text,            # what the user said, for the resolver
        "usd": usd,
        "all": bool(obj.get("all")),
        "hours": hours,
    }


def map_execute_result(status_code, body):
    """Translate a Bankr /wallet/swap response into what we say.

    Returns (status, spoken) where status is one of
    done | reverted | refused | unknown | error.
    """
    if status_code == 200:
        if isinstance(body, dict) and body.get("success") is True and body.get("hash"):
            return "done", None
        return (
            "reverted",
            "It didn't go through. Nothing was exchanged, though a small gas fee was charged.",
        )
    if status_code == 504:
        return "unknown", "I'm not sure it went through. Check bankr dot bot before trying again."
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("error") or body.get("message") or "").lower()
    if status_code == 403:
        if "spend" in msg or "limit" in msg:
            return "refused", "That's over the daily limit you set on bankr dot bot."
        if "impact" in msg:
            return "refused", "The price would move too much for that trade right now."
        if "paused" in msg:
            return "refused", "Your wallet is paused on bankr dot bot."
        if "read" in msg:
            return "refused", "The trade key is read-only. Check the key settings on bankr dot bot."
        return "refused", "Bankr declined that trade."
    if status_code == 400:
        if "balance" in msg or "insufficient" in msg or "gas" in msg:
            return "refused", "There isn't enough in the wallet for that, including gas."
        return "refused", "Bankr couldn't place that trade."
    if status_code == 409:
        return "refused", "Another trade is still in progress. Give it a minute."
    if status_code == 429:
        return "refused", "Bankr is rate limiting us. Try again in a minute."
    if status_code in (500, 502, 503):
        return "error", "Bankr had a problem placing the trade."
    return "error", "Bankr returned an unexpected response."


def swap_error_reason(status_code, body):
    """Quote failures. Same idea, quote-specific wording."""
    msg = ""
    if isinstance(body, dict):
        msg = str(body.get("error") or body.get("message") or "").lower()
    if status_code == 400 and "small" in msg:
        return "That amount is too small to trade."
    if status_code == 401:
        return "Bankr rejected the key. Check it in Settings."
    if status_code == 403:
        return "Bankr won't quote that token right now."
    return "I couldn't get a price from Bankr right now."


# -----------------------------------------------------------------------------
# Bankr calls (blocking; always called via asyncio.to_thread)
# -----------------------------------------------------------------------------

def _headers(key):
    return {"X-API-Key": key, "Content-Type": "application/json"}


def bankr_swap_quote(read_key, quote_req):
    r = requests.post(
        f"{BANKR_API}/wallet/swap-quote",
        headers=_headers(read_key),
        json=quote_req,
        timeout=READ_TIMEOUT,
    )
    return r.status_code, _safe_json(r)


def bankr_swap(trade_key, quote_req, min_buy_amount, quote_id, idempotency_key):
    body = dict(quote_req)
    body["minBuyAmount"] = str(min_buy_amount)
    if quote_id:
        body["quoteId"] = quote_id
    body["idempotencyKey"] = idempotency_key
    r = requests.post(
        f"{BANKR_API}/wallet/swap",
        headers=_headers(trade_key),
        json=body,
        timeout=EXECUTE_TIMEOUT,
    )
    return r.status_code, _safe_json(r)


RESOLVER_PROMPT = """You are a token lookup service. Reply with JSON only, no prose, no code fences.
Find tokens on the Base network (chain id 8453) that match the spoken name: "{asset_text}".
Return: {{"candidates":[{{"name":"","symbol":"","address":"0x...","decimals":18,
 "price_usd":0.0,"market_cap_usd":0.0,"change_24h_pct":0.0,"confidence":0.0}}]}}
Rules: up to 3 candidates, best first, confidence 0-1. Only tokens with a Base contract.
Do not execute, quote, or trade anything. If nothing matches, return {{"candidates":[]}}."""


def bankr_agent_prompt(read_key, prompt):
    r = requests.post(
        f"{BANKR_API}/agent/prompt",
        headers=_headers(read_key),
        json={"prompt": prompt},
        timeout=READ_TIMEOUT,
    )
    return r.status_code, _safe_json(r)


def _safe_json(resp):
    try:
        return resp.json()
    except ValueError:
        return {"error": (resp.text or "")[:200]}


def parse_coingecko(data):
    """{asset: (usd_price, 24h_change_pct)} from CoinGecko's simple/price body."""
    out = {}
    for key, a in ASSETS.items():
        row = (data or {}).get(a["coingecko"]) or {}
        if "usd" in row:
            out[key] = (Decimal(str(row["usd"])), row.get("usd_24h_change"))
    return out


# -----------------------------------------------------------------------------
# The ability
# -----------------------------------------------------------------------------

class OpenhomeBankrCapability(MatchingCapability):
    worker: AgentWorker = None
    capability_worker: CapabilityWorker = None
    # MatchingCapability is a pydantic model: every instance attribute must be
    # declared here or assignment raises "object has no field".
    read_key: str = None
    trade_key: str = None
    can_trade: bool = False
    resolve_cache: dict = None
    agent_unavailable: bool = False

    # Do not change following tag of register capability
    # {{register capability}}

    def call(self, worker: AgentWorker):
        self.worker = worker
        self.capability_worker = CapabilityWorker(self.worker)
        self.worker.session_tasks.create(self.run())

    # --- logging shorthands -------------------------------------------------
    def _info(self, msg):
        self.worker.editor_logging_handler.info(f"[Bankr] {msg}")

    def _warn(self, msg):
        self.worker.editor_logging_handler.warning(f"[Bankr] {msg}")

    def _error(self, msg):
        self.worker.editor_logging_handler.error(f"[Bankr] {msg}")

    async def _say(self, text):
        await self.capability_worker.speak(text)

    # --- HTTP GETs go through the platform's session_tasks wrapper -----------
    def _bankr_portfolio(self):
        r = self.worker.session_tasks.get(
            f"{BANKR_API}/wallet/portfolio",
            headers=_headers(self.read_key),
            params={"chains": CHAIN, "showLowValueTokens": "true"},
            timeout=READ_TIMEOUT,
        )
        return r.status_code, _safe_json(r)

    def _coingecko_prices(self):
        """Free, no key. Returns {} on any failure so callers degrade gracefully."""
        try:
            ids = ",".join(a["coingecko"] for a in ASSETS.values())
            r = self.worker.session_tasks.get(
                COINGECKO_PRICE,
                params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
                timeout=READ_TIMEOUT,
            )
            if r.status_code != 200:
                return {}
            return parse_coingecko(r.json())
        except Exception as e:
            self._warn(f"coingecko: {e!r}")
            return {}

    def _bankr_job(self, job_id):
        r = self.worker.session_tasks.get(
            f"{BANKR_API}/agent/job/{job_id}", headers=_headers(self.read_key), timeout=READ_TIMEOUT
        )
        return r.status_code, _safe_json(r)

    def _dexscreener_resolve(self, asset_text):
        q = sanitize_asset_text(asset_text)
        r = self.worker.session_tasks.get(DEXSCREENER_SEARCH, params={"q": q}, timeout=READ_TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"dexscreener {r.status_code}")
        body = r.json() or {}
        hits = len(body.get("pairs") or [])
        return dexscreener_candidates(body, q), hits

    def _coingecko_resolve(self, asset_text):
        """Search CoinGecko, take the top few by market-cap rank, keep those with
        a Base contract. Returns a candidate list ([] if nothing usable)."""
        q = sanitize_asset_text(asset_text)
        r = self.worker.session_tasks.get(COINGECKO_SEARCH, params={"query": q}, timeout=READ_TIMEOUT)
        if r.status_code != 200:
            raise RuntimeError(f"search {r.status_code}")
        coins = (r.json() or {}).get("coins") or []
        hits = len(coins)
        coins = sorted(coins, key=lambda c: (c.get("market_cap_rank") is None, c.get("market_cap_rank") or 0))[:4]
        out = []
        for i, c in enumerate(coins):
            cid = str(c.get("id") or "")
            if not cid:
                continue
            d = self.worker.session_tasks.get(
                COINGECKO_COIN + cid,
                params={"localization": "false", "tickers": "false", "community_data": "false",
                        "developer_data": "false", "sparkline": "false"},
                timeout=READ_TIMEOUT,
            )
            if d.status_code != 200:
                self._warn(f"coingecko coin {cid}: {d.status_code} {d.text[:120]}")
                continue
            cand = coingecko_candidate(d.json(), q, len(out))
            if cand is None:
                self._info(f"coingecko coin {cid}: no Base contract or unusable data")
            if cand:
                out.append(cand)
            if len(out) >= 3:
                break
        return out, hits

    async def _bankr_agent_resolve(self, asset_text):
        """Optional fallback: Bankr's agent with the READ key. Needs Bankr Club
        or Max Mode on the account; returns [] (never an error) when unavailable."""
        if self.agent_unavailable:
            return []
        prompt = RESOLVER_PROMPT.format(asset_text=sanitize_asset_text(asset_text))
        code, body = await asyncio.to_thread(bankr_agent_prompt, self.read_key, prompt)
        if code not in (200, 202) or not isinstance(body, dict) or not body.get("jobId"):
            self._info(f"agent resolve unavailable ({code}): {str(body)[:120]}")
            if code in (401, 403):
                self.agent_unavailable = True
            return []
        deadline = time.time() + RESOLVE_TIMEOUT_S
        while time.time() < deadline:
            await self.worker.session_tasks.sleep(2.0)
            code, job = await asyncio.to_thread(self._bankr_job, body["jobId"])
            status = (job.get("status") if isinstance(job, dict) else None) or ""
            if status == "completed":
                return parse_resolver_json(job.get("response"))
            if status in ("failed", "cancelled"):
                return []
        return []

    async def _resolve_token(self, asset_text):
        """(status, payload) per pick_candidate, or ('error', spoken_reason)."""
        key = _norm(asset_text)
        if self.resolve_cache is None:
            self.resolve_cache = {}
        if key not in self.resolve_cache:
            cands, hits = [], 0
            try:
                cands, hits = await asyncio.to_thread(self._dexscreener_resolve, asset_text)
            except Exception as e:
                self._warn(f"dexscreener resolve: {e!r}")
            if not cands:
                try:
                    cands, hits2 = await asyncio.to_thread(self._coingecko_resolve, asset_text)
                    hits = hits or hits2
                except Exception as e:
                    self._warn(f"coingecko resolve: {e!r}")
            if not cands:
                cands = await self._bankr_agent_resolve(asset_text)
            self._info(f"resolve {asset_text!r} -> {[(c['symbol'], c['address'][:10], str(c['market_cap'])) for c in cands]} (search hits {hits})")
            self.resolve_cache[key] = (cands, hits)
        cands, hits = self.resolve_cache[key]
        status, payload = pick_candidate(cands)
        if status == "none" and hits:
            # Search found the name somewhere, but nothing usable on Base.
            return "not_on_base", None
        return status, payload

    async def _token_for(self, intent, side, holdings=None):
        """Resolve the intent's asset to a token record, asking one clarifying
        question if needed. Returns the record or None (already spoken)."""
        nothing = "Nothing was traded."
        if intent["asset"] in ("BTC", "ETH"):
            return menu_token(intent["asset"])
        if intent["asset"] == "USD":
            await self._say(f"Dollars are what you {side} with. Name a token. {nothing}")
            return None
        text = intent.get("asset_text") or ""
        if not text:
            await self._say(f"Which token? {nothing}")
            return None
        if side == "sell":
            status, payload = match_holding(text, holdings or {})
            if status == "none":
                await self._say(f"You don't hold anything called {text}. {nothing}")
                return None
            if status == "ambiguous":
                a, b = payload
                reply = await self.capability_worker.run_io_loop(f"{a['name']} or {b['name']}?")
                status, payload = match_holding(reply, {a["address"]: a, b["address"]: b})
                if status != "ok":
                    await self._say(f"Cancelled. {nothing}")
                    return None
            return payload
        status, payload = await self._resolve_token(text)
        if status == "error":
            await self._say(f"{payload} {nothing}")
            return None
        if status == "none":
            await self._say(f"I couldn't find a token called {text}. {nothing}")
            return None
        if status == "not_on_base":
            await self._say(f"{text.title()} exists, but not on Base, which is the only network I trade on. {nothing}")
            return None
        if status == "small":
            await self._say(f"{payload['name']} is too small or too thinly traded for me to trade by voice. {nothing}")
            return None
        if status == "ambiguous":
            a, b = payload
            reply = await self.capability_worker.run_io_loop(f"{a['name']}, ticker {a['symbol']}, or {b['name']}, ticker {b['symbol']}?")
            st, pick = match_holding(reply, {a["address"]: a, b["address"]: b})
            if st != "ok":
                await self._say(f"Cancelled. {nothing}")
                return None
            return pick
        return payload

    # --- entry --------------------------------------------------------------
    async def run(self):
        try:
            read_key = self.capability_worker.get_api_keys(READ_KEY_NAME)
            trade_key = self.capability_worker.get_api_keys(TRADE_KEY_NAME)
            if not read_key:
                await self._say(
                    "Your Bankr wallet isn't linked yet. On bankr dot bot, create a read-only "
                    "API key and add it in Settings under API Keys as bankr underscore read "
                    "underscore key. Add a wallet key as bankr underscore trade underscore key "
                    "if you want to trade by voice."
                )
                return
            self.read_key, self.trade_key = read_key, trade_key
            self.can_trade = bool(trade_key)

            intent = await self._get_intent()
            if intent is None:
                return
            action = intent["action"]
            self._info(f"intent action={action} asset={intent['asset']} usd={intent['usd']} all={intent['all']}")

            if action == "cancel":
                await self._say("Okay. Nothing was traded.")
            elif action in ("help", "unknown"):
                await self._help()
            elif action == "price":
                await self._price(intent)
            elif action == "portfolio":
                await self._portfolio()
            elif action == "lock":
                await self._lock(intent)
            elif action in ("buy", "sell"):
                await self._trade(intent)
        except Exception as e:  # never leave the agent stuck
            self._error(f"unhandled: {e!r}")
            try:
                await self._say("Something went wrong on my side. Nothing was traded.")
            except Exception:
                pass
        finally:
            self.capability_worker.resume_normal_flow()

    # --- intent -------------------------------------------------------------
    async def _last_user_utterance(self):
        """The full sentence that triggered us.

        The conversation history is only appended after the ability finishes,
        so it can't be used here. The SDK's documented way to capture the
        trigger sentence is wait_for_complete_transcription() as the first
        step; the worker's transcription attributes are the fallback.
        """
        try:
            text = await self.capability_worker.wait_for_complete_transcription()
            if text and text.strip():
                return text.strip()
        except Exception as e:
            self._warn(f"wait_for_complete_transcription: {e!r}")
        try:
            if self.worker.transcription and str(self.worker.transcription).strip():
                return str(self.worker.transcription).strip()
        except Exception:
            pass
        try:
            if self.worker.last_transcription and str(self.worker.last_transcription).strip():
                return str(self.worker.last_transcription).strip()
        except Exception:
            pass
        return ""

    def _extract(self, utterance):
        raw = self.capability_worker.text_to_text_response(
            f"Sentence: {utterance!r}", system_prompt=INTENT_SYSTEM_PROMPT
        )
        return parse_intent_json(raw)

    async def _get_intent(self):
        utterance = await self._last_user_utterance()
        intent = self._extract(utterance) if utterance else None
        if intent and intent["action"] not in ("unknown", "help"):
            return intent
        # Trigger phrase alone ("open my wallet") or a parse miss: ask once.
        reply = await self.capability_worker.run_io_loop(
            "Bankr here. You can ask for a price, your portfolio, or say buy or sell "
            "with a dollar amount. What would you like?"
        )
        if not reply:
            await self._say("I didn't catch that. Nothing was traded.")
            return None
        intent = self._extract(reply)
        if not intent or intent["action"] == "unknown":
            await self._say(
                "I only do prices, your portfolio, and buying or selling Bitcoin or "
                "Ethereum in dollars. Nothing was traded."
            )
            return None
        return intent

    async def _help(self):
        await self._say(
            "I can tell you what a token is at, read your portfolio, or buy and sell any "
            f"token on Base in dollars, up to {usd_words(VOICE_MAX_PER_TRADE_USD)} a trade. "
            "Say lock my wallet to pause me. Everything else lives on bankr dot bot."
        )

    # --- reads --------------------------------------------------------------
    async def _price(self, intent):
        key = intent["asset"]
        if key == "USD" or (key is None and not intent.get("asset_text")):
            key = "BTC"
        if key in ("BTC", "ETH"):
            prices = await asyncio.to_thread(self._coingecko_prices)
            if key not in prices:
                await self._say("I couldn't get a price right now.")
                return
            price, change = prices[key]
            name = ASSETS[key]["name"]
        else:
            status, payload = await self._resolve_token(intent["asset_text"])
            if status == "error":
                await self._say(payload)
                return
            if status == "none":
                await self._say(f"I couldn't find a token called {intent['asset_text']}.")
                return
            if status == "not_on_base":
                await self._say(f"{intent['asset_text'].title()} exists, but not on Base, which is the only network I track.")
                return
            if status == "small":
                await self._say(
                    f"The closest match on Base is {payload['name']}, which is too small or too "
                    "thinly traded for me. I don't quote it."
                )
                return
            if status == "ambiguous":
                a, b = payload
                await self._say(
                    f"Two matches. {a['name']}, ticker {a['symbol']}, is at {price_words(a['ref_price'])}. "
                    f"{b['name']}, ticker {b['symbol']}, is at {price_words(b['ref_price'])}."
                )
                return
            tok = payload
            price, change, name = tok["ref_price"], tok["change_24h"], tok["name"]
        line = f"{name} is at {price_words(price)}"
        if change is not None:
            pct = Decimal(str(change)).quantize(Decimal("0.1"))
            direction = "up" if pct >= 0 else "down"
            line += f", {direction} {abs(pct)} percent today"
        await self._say(line + ".")

    async def _portfolio(self):
        code, body = await asyncio.to_thread(self._bankr_portfolio)
        if code == 401:
            await self._say("Bankr rejected the read key. Check it in Settings.")
            return
        if code != 200 or not isinstance(body, dict):
            self._warn(f"portfolio {code}: {str(body)[:200]}")
            await self._say("I can't reach your Bankr wallet right now.")
            return
        holdings = self._holdings(body)
        total = sum(v["usd"] for v in holdings.values())
        if total == 0:
            await self._say(
                "Your wallet is empty on Base. Send USDC there from bankr dot bot to get started."
            )
            return
        parts = []
        ranked = sorted(holdings.values(), key=lambda h: h["usd"], reverse=True)
        for h in [h for h in ranked if h["usd"] >= Decimal("0.5")][:5]:
            if h.get("key") == "USD":
                parts.append(f"{rounded_usd_words(h['usd'])} in cash")
            else:
                parts.append(f"{rounded_usd_words(h['usd'])} of {h['name']}")
        summary = f"You have {rounded_usd_words(total)} on Base"
        if parts:
            summary += ": " + ", ".join(parts)
        await self._say(summary + ".")

    def _holdings(self, portfolio):
        """{address_lower: token record + amount/usd/price} for every Base holding.
        Menu tokens are also reachable via holding_for_key()."""
        out = {}
        chain = ((portfolio.get("balances") or {}).get(CHAIN)) or {}
        native = chain.get("nativeBalance")
        if native is not None:
            amt = _dec(native)
            usd = _dec(chain.get("nativeUsd"))
            rec = menu_token("ETH")
            rec.update({"amount": amt, "usd": usd, "price": (usd / amt) if amt else None})
            out[rec["address"].lower()] = rec
        for entry in chain.get("tokenBalances") or []:
            tok = (entry or {}).get("token") or {}
            base = tok.get("baseToken") or {}
            addr = str(base.get("address") or "").lower()
            if not _ADDR_RE.match(addr):
                continue
            amt = _dec(tok.get("balance"))
            usd = _dec(tok.get("balanceUSD"))
            price = _dec(base.get("price")) if base.get("price") is not None else (usd / amt if amt else None)
            rec = None
            for key, a in ASSETS.items():
                if key != "ETH" and addr == a["address"].lower():
                    rec = menu_token(key)
            if rec is None:
                rec = {"name": sanitize_asset_text(base.get("name")).title() or str(base.get("symbol") or "token"),
                       "symbol": str(base.get("symbol") or "").upper()[:12], "address": addr,
                       "decimals": None, "ref_price": price, "market_cap": None, "change_24h": None,
                       "confidence": 1.0, "is_menu": False}
            rec.update({"amount": amt, "usd": usd, "price": price})
            out[addr] = rec
        return out

    @staticmethod
    def holding_for_key(holdings, key):
        return holdings.get(ASSETS[key]["address"].lower())

    # --- lock ---------------------------------------------------------------
    def _lock_state(self):
        try:
            v = self.capability_worker.get_single_key(KV_LOCK) or {}
        except Exception:
            return None
        until = v.get("until")
        if until and float(until) > time.time():
            return v
        return None

    def _set_kv(self, key, value):
        try:
            if self.capability_worker.get_single_key(key) is not None:
                self.capability_worker.update_key(key, value)
            else:
                self.capability_worker.create_key(key, value)
        except Exception as e:
            self._warn(f"kv write {key} failed: {e!r}")

    async def _lock(self, intent):
        hours = intent.get("hours")
        seconds = int(hours * 3600) if hours and hours > 0 else DEFAULT_LOCK_S
        seconds = min(seconds, 7 * 24 * 3600)
        self._set_kv(KV_LOCK, {"until": time.time() + seconds, "reason": "voice"})
        span = f"{int(seconds // 3600)} hours" if seconds >= 3600 else f"{int(seconds // 60)} minutes"
        await self._say(
            f"Locked. I won't trade for {span}. There's no voice unlock; to stop everything, "
            "use Pause on bankr dot bot."
        )

    # --- spend tracking (rolling 24h, voice-side only) ----------------------
    def _spent_24h(self):
        try:
            v = self.capability_worker.get_single_key(KV_SPEND) or {}
        except Exception:
            return Decimal("0"), []
        cutoff = time.time() - 24 * 3600
        entries = [e for e in (v.get("entries") or []) if float(e.get("t", 0)) > cutoff]
        total = sum((_dec(e.get("usd")) for e in entries), Decimal("0"))
        return total, entries

    def _record_spend(self, entries, usd):
        entries = list(entries) + [{"t": time.time(), "usd": str(usd)}]
        self._set_kv(KV_SPEND, {"entries": entries[-50:]})

    # --- trade --------------------------------------------------------------
    async def _trade(self, intent):
        side = intent["action"]
        nothing = "Nothing was traded."

        if not self.can_trade:
            await self._say(
                "I only have a read-only key, so I can't trade. Add a wallet key as bankr "
                f"underscore trade underscore key in Settings to enable it. {nothing}"
            )
            return
        lock = self._lock_state()
        if lock:
            await self._say(f"My trading is locked right now. {nothing}")
            return

        holdings = await self._load_holdings()
        if holdings is None:
            return
        tok = await self._token_for(intent, side, holdings)
        if tok is None:
            return
        name = tok["name"]
        held = holdings.get(tok["address"].lower())

        usd = intent["usd"]
        if side == "sell" and intent["all"]:
            if not held or held["amount"] <= 0:
                await self._say(f"You don't hold any {name} to sell. {nothing}")
                return
            if held["usd"] < MIN_SELL_ALL_USD:
                await self._say(f"Your {name} is only worth {about_usd_words(held['usd'])}, too little to sell. {nothing}")
                return
            usd = held["usd"].quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if usd is None:
            reply = await self.capability_worker.run_io_loop(
                f"How much, in dollars, would you like to {side}?"
            )
            usd = normalize_usd(reply)
            if usd is None:
                await self._say(f"I didn't get a clear dollar amount. {nothing}")
                return

        if usd < MIN_TRADE_USD and not (side == "sell" and intent["all"]):
            await self._say(f"The minimum is {usd_words(MIN_TRADE_USD)}. {nothing}")
            return
        if usd > VOICE_MAX_PER_TRADE_USD:
            await self._say(
                f"{usd_words(usd)} is above my voice limit of {usd_words(VOICE_MAX_PER_TRADE_USD)} "
                f"a trade. Use bankr dot bot for bigger trades. {nothing}"
            )
            return
        spent, entries = self._spent_24h()
        if spent + usd > VOICE_MAX_DAILY_USD:
            left = max(VOICE_MAX_DAILY_USD - spent, Decimal("0"))
            await self._say(
                f"That would go past my daily voice limit of {usd_words(VOICE_MAX_DAILY_USD)}. "
                f"You have {usd_words(left)} left today. {nothing}"
            )
            return

        # Reference price: CoinGecko for menu tokens, the resolver / portfolio otherwise.
        if tok["is_menu"]:
            ref = await asyncio.to_thread(self._coingecko_prices)
            ref_price = ref.get(tok["key"], (None, None))[0]
            drift_max = PRICE_DRIFT_MAX
        else:
            ref_price = tok.get("ref_price") or (held or {}).get("price")
            drift_max = PRICE_DRIFT_MAX_OTHER

        usdc = self.holding_for_key(holdings, "USD") or {}
        if side == "buy":
            cash = usdc.get("amount", Decimal("0"))
            if cash < usd:
                if cash < MIN_TRADE_USD:
                    await self._say(f"You don't have any cash in the wallet to buy with. {nothing}")
                    return
                cash = cash.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                reply = await self.capability_worker.run_io_loop(
                    f"You only have {usd_words(cash)} available. To buy that much instead, say the amount."
                )
                if normalize_usd(reply) != cash:
                    await self._say(f"Cancelled. {nothing}")
                    return
                usd = cash
            from_addr, to_addr, amount = ASSETS["USD"]["address"], tok["address"], usd
        else:
            if not held or held["amount"] == 0:
                await self._say(f"You don't hold any {name} to sell. {nothing}")
                return
            price = held["price"] or ref_price
            if not price:
                await self._say(f"I couldn't price your {name}. {nothing}")
                return
            if intent["all"]:
                amount = held["amount"]
            else:
                decimals = tok.get("decimals")
                if decimals is None:
                    decimals = 6
                amount = (usd / price).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)
                if amount > held["amount"]:
                    have = held["usd"].quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                    await self._say(
                        f"You only hold about {usd_words(have)} of {name}. "
                        f"Say sell all my {name} to sell it all. {nothing}"
                    )
                    return
            from_addr, to_addr = tok["address"], ASSETS["USD"]["address"]

        # Quote.
        quote_req = {
            "fromChain": CHAIN,
            "fromToken": from_addr,
            "toChain": CHAIN,
            "toToken": to_addr,
            "amount": format(Decimal(amount).normalize(), "f"),
            "slippageBps": 100,
        }
        quoted_at = time.time()
        code, q = await asyncio.to_thread(bankr_swap_quote, self.read_key, quote_req)
        if code != 200 or not isinstance(q, dict) or "minBuyAmount" not in q:
            self._warn(f"quote {code}: {str(q)[:200]}")
            await self._say(f"{swap_error_reason(code, q)} {nothing}")
            return

        try:
            out_amt = _dec((q.get("to") or {}).get("formattedAmount"))
            in_amt = _dec((q.get("from") or {}).get("formattedAmount") or quote_req["amount"])
            # Effective execution price = what you actually pay per coin. Bankr's
            # sellTokenPriceUsd / buyTokenPriceUsd are reference fields and have
            # been observed 14% stale, so they're only logged, never trusted.
            if side == "buy":
                quote_price = (in_amt / out_amt) if out_amt else Decimal("0")
            else:
                quote_price = (out_amt / in_amt) if in_amt else Decimal("0")
            self._info(
                f"quote: in={in_amt} out={out_amt} eff_price={format(quote_price.normalize(), 'f')[:14]} "
                f"ref_field={q.get('buyTokenPriceUsd') if side == 'buy' else q.get('sellTokenPriceUsd')} "
                f"impact_bps={q.get('priceImpactBps')} fee_bps={q.get('feeBps')} min={q.get('minBuyAmount')}"
            )
            if quote_price <= 0:
                raise ValueError("zero amount in quote")
        except Exception as e:
            self._warn(f"quote parse: {e!r}")
            await self._say(f"Bankr's quote looked wrong. {nothing}")
            return

        # Sanity: effective price vs an independent source.
        if ref_price:
            drift = abs(quote_price - ref_price) / ref_price
            if drift > drift_max:
                self._warn(f"price drift {drift:.3f}: effective {quote_price} vs ref {ref_price}")
                await self._say(f"Bankr's price looks off from the market right now. {nothing}")
                return
        # Our own impact figure: how much worse than the market price the user
        # gets. Bankr's priceImpactBps is relative to its (sometimes stale)
        # reference price, so it isn't spoken.
        impact_bps = 0
        if ref_price:
            worse = (quote_price - ref_price) if side == "buy" else (ref_price - quote_price)
            impact_bps = max(int(worse / ref_price * 10000), 0)
        fee_bps = int(q.get("feeBps") or 0)

        # Read-back. The user confirms by repeating the DOLLAR amount.
        if side == "buy":
            readback = (
                f"{usd_words(usd)} gets you {asset_words(out_amt, name)} at "
                f"{price_words(quote_price)}" + (" each" if not tok["is_menu"] else "") + "."
            )
        else:
            readback = (
                f"Selling {asset_words(amount, name)} for {about_usd_words(out_amt)} at "
                f"{price_words(quote_price)}" + (" each" if not tok["is_menu"] else "") + "."
            )
        if impact_bps > 100:
            readback += f" Price impact is {Decimal(impact_bps) / 100} percent."
        if fee_bps > 100:
            readback += f" Bankr's fee is {Decimal(fee_bps) / 100} percent."
        readback += " To confirm, say the amount."

        heard = await self.capability_worker.run_io_loop(readback)
        confirm_target = usd if side == "buy" else out_amt.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        heard_usd = normalize_usd(heard)
        ok = heard_usd is not None and (
            heard_usd == confirm_target
            or (side == "sell" and abs(heard_usd - confirm_target) <= Decimal("1.00"))
        )
        if not ok:
            self._info(f"mismatch: heard={heard!r} -> {heard_usd} target={confirm_target}")
            self._note_mismatch()
            await self._say(f"Cancelled. {nothing}")
            return

        # Freshness. If the quote aged out, re-quote and make them confirm again.
        if time.time() - quoted_at > QUOTE_MAX_AGE_S:
            await self._say("That quote expired while we talked. Let me get a fresh one.")
            code, q2 = await asyncio.to_thread(bankr_swap_quote, self.read_key, quote_req)
            if code != 200 or not isinstance(q2, dict) or "minBuyAmount" not in q2:
                await self._say(f"{swap_error_reason(code, q2)} {nothing}")
                return
            q = q2
            out_amt = _dec((q.get("to") or {}).get("formattedAmount"))
            line = (
                f"Now {usd_words(usd)} gets you {asset_words(out_amt, name)}."
                if side == "buy"
                else f"Now that's {about_usd_words(out_amt)}."
            )
            heard = await self.capability_worker.run_io_loop(line + " Say the amount once more to confirm.")
            if normalize_usd(heard) != (usd if side == "buy" else out_amt.quantize(Decimal("0.01"), rounding=ROUND_DOWN)):
                await self._say(f"Cancelled. {nothing}")
                return

        # Execute. One intent id, one idempotency key.
        intent_id = str(uuid.uuid4())
        self._info(f"execute intent={intent_id} side={side} token={tok['symbol']} usd={usd}")
        code, body = await asyncio.to_thread(
            bankr_swap, self.trade_key, quote_req, q["minBuyAmount"], q.get("quoteId"), intent_id
        )
        status, spoken = map_execute_result(code, body)
        self._info(f"execute intent={intent_id} -> {status} ({code})")

        if status == "done":
            self._record_spend(entries, usd)
            # Speak what Bankr says actually moved; the portfolio endpoint lags
            # a few seconds behind a swap, so it isn't used for this line.
            got = _dec(body.get("amountReceived")) if isinstance(body, dict) else Decimal("0")
            if side == "buy":
                line = f"Done. You bought {asset_words(got or out_amt, name)} for {usd_words(usd)}."
            else:
                line = f"Sold. You got {about_usd_words(got or out_amt)}."
            await self._say(line)
        elif status == "unknown":
            self._record_spend(entries, usd)  # assume the worst for the cap
            await self._say(spoken)
        else:
            await self._say(f"{spoken} {nothing}")

    async def _load_holdings(self, quiet=False):
        code, body = await asyncio.to_thread(self._bankr_portfolio)
        if code != 200 or not isinstance(body, dict):
            self._warn(f"portfolio {code}: {str(body)[:200]}")
            if not quiet:
                await self._say("I can't reach your Bankr wallet right now. Nothing was traded.")
            return None
        return self._holdings(body)

    def _note_mismatch(self):
        try:
            v = self.capability_worker.get_single_key("openhome_bankr_mismatch") or {}
        except Exception:
            v = {}
        recent = [t for t in (v.get("t") or []) if float(t) > time.time() - 600]
        recent.append(time.time())
        self._set_kv("openhome_bankr_mismatch", {"t": recent[-5:]})
        if len(recent) >= 2:
            self._set_kv(KV_LOCK, {"until": time.time() + MISMATCH_PAUSE_S, "reason": "mismatch"})
            self._warn("two mismatches; trading paused 15 minutes")


def _dec(v):
    if v is None or v == "":
        return Decimal("0")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return Decimal("0")
