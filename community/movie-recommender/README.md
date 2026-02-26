# Movie & TV Recommender

Recommends movies using The Movie Database (TMDB) API. Supports trending movies, genre/mood-based search, and finding movies similar to ones you like.

## Triggers

- "movie recommendation"
- "recommend a movie"
- "what should I watch"
- "movie suggestion"
- "trending movies"

## Features

- Trending movies of the week
- Genre and mood-based discovery (e.g., "something scary", "a funny movie")
- Similar movie suggestions ("movies like Inception")
- Title, year, rating, and one-line summary for each recommendation
- Multi-turn conversation for browsing

## Setup

Requires a free TMDB API key:

1. Create an account at https://www.themoviedb.org/
2. Go to Settings > API and request an API key
3. Add API key in line 21.

Note: Use the API Read Access Token (v4 auth), not the v3 API key.

## Example Usage

> "What's trending in movies?"
> "Recommend something scary"
> "Movies like The Matrix"
> "I want a romantic comedy"
