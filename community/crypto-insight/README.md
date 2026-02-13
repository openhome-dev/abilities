# Crypto Insight

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@pipinstallshan-lightgrey?style=flat-square)

## What It Does

Provides real-time cryptocurrency price analysis with technical indicators (RSI and SMA) using live data from CoinGecko. Get instant insights on price movements, momentum, and trend direction through voice commands.

## Suggested Trigger Words

- "crypto insight"
- "check crypto"
- "what's bitcoin doing"
- "crypto price"
- "check ethereum"
- "bitcoin price"
- "ethereum price"
- "crypto analysis"

## Setup

**No API keys required!** This ability uses CoinGecko's free public API, which doesn't require authentication.

## How It Works

1. You ask about a cryptocurrency (e.g., "What's Bitcoin doing?")
2. The ability extracts the crypto name from your request
3. It fetches live price data and historical candles from CoinGecko
4. Calculates technical indicators:
   - **RSI (14-period)**: Momentum indicator showing overbought/oversold conditions
   - **SMA (7-day)**: Moving average for trend direction
5. Delivers a natural, voice-friendly summary

## Technical Details

### RSI (Relative Strength Index)
- **Range**: 0-100
- **Oversold**: RSI < 30 (potential buying opportunity)
- **Overbought**: RSI > 70 (potential selling pressure)
- **Neutral**: RSI 30-70 (balanced momentum)

### SMA (Simple Moving Average)
- **7-day period**: Short-term trend indicator
- **Bullish**: Price above SMA (uptrend)
- **Bearish**: Price below SMA (downtrend)

### Supported Cryptocurrencies

The ability supports any cryptocurrency available on CoinGecko, including:
- Bitcoin (BTC)
- Ethereum (ETH)
- Dogecoin (DOGE)
- Cardano (ADA)
- Solana (SOL)
- Ripple (XRP)
- Polkadot (DOT)
- Litecoin (LTC)
- Chainlink (LINK)
- Polygon (MATIC)
- And many more!

## Example Conversations

### Example 1: Bitcoin Analysis

> **User:** "What's Bitcoin doing?"
>
> **AI:** "Let me check bitcoin for you."
>
> **AI:** "Bitcoin is trading at $42,150, up 3.2% in 24 hours. RSI is 58, suggesting neutral momentum. Price is above the 7-day average by 2.3%, indicating bullish trend."

### Example 2: Ethereum Check

> **User:** "Check Ethereum"
>
> **AI:** "Let me check ethereum for you."
>
> **AI:** "Ethereum is trading at $2,234.56, down 1.8% in 24 hours. RSI is 72, suggesting overbought, possibly indicating a potential correction. Price is above the 7-day average by 5.1%, indicating bullish trend."

### Example 3: Dogecoin Query

> **User:** "Crypto insight"
>
> **AI:** "Which cryptocurrency would you like to check?"
>
> **User:** "Dogecoin"
>
> **AI:** "Let me check dogecoin for you."
>
> **AI:** "Dogecoin is trading at $0.0845, up 7.3% in 24 hours. RSI is 28, suggesting oversold, possibly indicating a buying opportunity. Price is below the 7-day average by 3.2%, indicating bearish trend."

## Data Sources

- **Price Data**: CoinGecko `/simple/price` endpoint
- **OHLC Data**: CoinGecko `/coins/{id}/ohlc` endpoint (14-day candles)
- **API Rate Limits**: CoinGecko free tier allows 10-50 calls/minute

## Limitations

- **Data Delay**: CoinGecko updates every ~5 minutes (not real-time tick data)
- **Free Tier**: Rate limits apply; heavy usage may require waiting
- **Not Financial Advice**: This ability provides informational insights only
- **Popular Coins**: Works best with top cryptocurrencies; obscure tokens may have limited data

## Error Handling

The ability gracefully handles:
- Invalid cryptocurrency names (suggests checking spelling)
- API failures (retries and provides user-friendly messages)
- Rate limiting (informs user to try again later)
- Missing data (falls back to price-only analysis)

## Voice-First Design

Responses are optimized for voice interaction:
- Concise, 2-3 sentence summaries
- Natural language (no technical jargon overload)
- Clear price formatting (handles cents to thousands appropriately)
- Actionable insights (bullish/bearish, overbought/oversold)

## Contributing

Found a bug or have a suggestion? Open an issue on the [GitHub repository](https://github.com/openhome-dev/abilities/issues).

## License

MIT License - See [LICENSE](../../LICENSE) for details.

---

**Disclaimer**: This ability provides informational analysis only and should not be considered financial advice. Cryptocurrency investments are highly volatile and risky. Always do your own research and consult with financial professionals before making investment decisions.
