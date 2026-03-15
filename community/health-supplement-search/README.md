# Health Supplement Search

Voice-driven semantic search over 100 curated health supplement products. Ask about a health concern and get personalized supplement recommendations backed by real product data and user reviews.

## What It Does

- Searches a curated database of 100 real supplement products from iHerb using semantic vector similarity
- Falls back to live web search (Serper API) when a supplement isn't in the local database
- Supports multi-turn conversation: ask for details, re-rank by rating, or search for something new
- Works with **Qdrant Cloud** or **Weaviate** as the vector database (switchable via a constant in `main.py`)

## Suggested Trigger Words

- "search for supplements"
- "supplement search"
- "find me a supplement"
- "health supplement advisor"
- "what supplements help with"

## Example Conversation

> **User:** "Find me supplements for joint pain"
> **AI:** "I found 3 great options. First, Glucosamine Sulfate by Doctor's Best, rated 4.6 out of 5, known for cartilage support and joint mobility. Second, Boswellia Extract by Now Foods, rated 4.4, with strong anti-inflammatory effects. Would you like more details on any of these?"

> **User:** "Tell me more about the first one"
> **AI:** "Doctor's Best Glucosamine Sulfate contains 750mg of pharmaceutical-grade glucosamine per capsule..."

> **User:** "What about something for sleep?"
> **AI:** "Let me search for that..."

## Required Setup (One-Time)

This ability needs a vector database pre-loaded with supplement data.

**Setup scripts and full instructions are in the companion branch:**
[`feat/health-supplement-search-setup`](https://github.com/megz2020/abilities/tree/feat/health-supplement-search-setup)

**Quick summary:**
1. Get a free [Weaviate Cloud](https://console.weaviate.cloud) cluster (built-in embeddings — no extra embedding API needed)
   — or a free [Qdrant Cloud](https://cloud.qdrant.io) cluster + [Jina AI](https://jina.ai/embeddings/) key
2. Clone the setup branch and run `python setup_vectordb.py --provider weaviate` (or `qdrant`) to load the 100 products
3. Optional: get a free [Serper](https://serper.dev) API key for web fallback (2,500 free searches/month)

## Configuration

Open `main.py` and fill in the constants at the top before uploading to OpenHome:

```python
# Choose your vector DB provider: "weaviate" or "qdrant"
VECTOR_DB_PROVIDER = "weaviate"

# Weaviate (no Jina key needed — embeddings are built-in)
WEAVIATE_URL = "https://xxx.weaviate.cloud"
WEAVIATE_API_KEY = "your-weaviate-api-key"
WEAVIATE_CLASS = "Supplement"          # keep as-is unless you changed it in setup

# Qdrant (requires Jina for embeddings)
QDRANT_URL = "https://xxx.qdrant.io:6333"
QDRANT_API_KEY = "your-qdrant-api-key"
QDRANT_COLLECTION = "supplements"      # keep as-is unless you changed it in setup
JINA_API_KEY = "jina_xxxx"             # only needed for Qdrant

# Serper web fallback (optional — leave empty to disable)
SERPER_API_KEY = ""                    # get a free key at serper.dev (2,500/month)
```

Set `VECTOR_DB_PROVIDER` to `"qdrant"` or `"weaviate"` to switch backends. Only fill in the keys for the provider you're using.

## How It Works

1. User speaks a health concern
2. **Weaviate path**: query is sent as text — Weaviate embeds it internally using Snowflake Arctic (free, built-in)
   **Qdrant path**: query is embedded into a 1536-dim vector via Jina AI, then sent to Qdrant
3. The vector DB returns the most similar supplement products (cosine similarity)
4. If no good match is found (distance >= threshold), falls back to Serper web search
5. Results are summarized by the OpenHome LLM into a natural voice response

## Vector DB Options

| Option | Free Tier | Best For |
|--------|-----------|----------|
| **Weaviate Cloud** | 14-day sandbox, then deleted | Quick testing — no extra embedding API needed |
| **Qdrant Cloud** | 1GB forever, auto-suspends after 1 week idle | Long-term production use |

> **Qdrant note**: The free cluster auto-suspends after 1 week without traffic. It auto-resumes on the next API call, but the first request after a pause may be slow.

## Key SDK Methods Used

- `speak()` — deliver responses to the user
- `user_response()` — listen for user input
- `text_to_text_response()` — LLM summarization and intent detection

## Data Source

Supplement data from the [Weaviate HealthSearch Demo](https://github.com/weaviate/healthsearch-demo) — 100 real products from iHerb with names, brands, ratings, reviews, ingredients, and health effects.

> **Disclaimer**: This ability is for informational purposes only and does not constitute medical advice. Always consult a qualified healthcare provider before starting any supplement.
