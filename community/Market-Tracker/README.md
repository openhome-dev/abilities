
Stock Portfolio & Market Data Capability
An advanced agent capability that allows users to track their stock portfolios, get real-time price updates, and receive voice-optimized market briefings.
🚀 Features
Persistent Portfolio Storage: Saves user stock lists to a JSON file (user_portfolio_v16.json) that persists across sessions.
Real-Time Data Engine: Integrates with the Finnhub API for live market quotes, with a fallback to LLM-based search for broader queries.
Natural Language Processing: Uses fuzzy logic to map company names (e.g., "Apple", "Tesla") to their respective tickers (AAPL, TSLA).

API Keys
The capability requires a Finnhub Token. You can update the FINNHUB_TOKEN class variable within the StockCapability class.

Dependencies
requests: For API communication.
json, re, os: Standard Python libraries for data and logic handling.
MatchingCapability, AgentWorker, CapabilityWorker: Core framework components.
🔧 Technical Logic
Persistent Storage Pattern
The capability follows a strict Read -> Modify -> Delete -> Write pattern to manage its JSON storage. This prevents data corruption or unintended appending within the file system.
TTS Engine
The _format_decimal_for_tts method uses regex to intercept numeric strings and inject "point" pronunciation. This is specifically paired with VOICE_ID: 29vD33N1CtxCmqQRPOHJ (News-style voice) for a professional financial reporting feel.
🖥️ Usage Examples
User Intent
Voice Command
(To Trigger)
Market
Add Stock
"Add Symbol Name(T S L A) to my Portfolio"
Check Price
"What is the current price of TESLA?"
Remove Stock
"Remove Tesla from my portfolio."

Note: The PERSIST flag is currently set to False (logic within this framework treats False as persistent). Adjust the FILENAME variable to version-control your data storage.

