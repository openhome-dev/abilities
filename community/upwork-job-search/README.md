# Upwork Job Search

![Abilities Badge](https://img.shields.io/badge/Abilities-Open-green.svg)io%2Fbadge%2FAbilities-Open-green)
![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-@khushi0433-lightgrey?style=flat-square)

## What It Does
Search for freelance jobs on Upwork using voice. Simply say what type of job you're looking for (like "web development" or "Python programming"), and this Ability will find the top Upwork jobs and read them out to you.

## Suggested Trigger Words
- "find jobs"
- "search upwork"
- "find freelance work"
- "upwork jobs"
- "look for work"

## Setup

### Prerequisites
- An Upwork API application registered at [developers.upwork.com](https://developers.upwork.com)

### API Credentials
1. Go to [developers.upwork.com](https://developers.upwork.com) and create a new app
2. Get your **Client Key** and **Client Secret**
3. Edit `main.py` and replace:
   
```
python
   UPWORK_CLIENT_KEY = "YOUR_UPWORK_CLIENT_KEY"
   UPWORK_CLIENT_SECRET = "YOUR_UPWORK_CLIENT_SECRET"
   
```

### How to Get Upwork API Access
1. Register at [developers.upwork.com](https://developers.upwork.com)
2. Create a new application with:
   - App Name: `OpenHome Upwork Jobs`
   - Description: Voice AI ability to search Upwork jobs
   - Callback URL: `https://localhost/callback`
   - App URL: `https://app.openhome.com`
3. Once approved, you'll receive Client Key and Client Secret
4. For production use, you'll need to implement proper OAuth 2.0 flow

## How It Works

```
User activates ability with trigger word
     Ability asks "What type of jobs are you looking for?"
     User responds with a category (e.g., "web development")
     Ability searches Upwork API
     Ability reads out top job results with:
        - Job title
        - Budget
        - Duration
        - Workload
        - Client rating
    → User can search again or exit
```

## Example Conversation

> User: "find jobs"
> AI: "I can help you find freelance jobs on Upwork. What type of jobs are you looking for? For example, web development, mobile app, data entry, or copy writing."
> User: "web development"
> AI: "Searching for web development jobs on Upwork... I found 5 jobs matching 'web development'. Here are the top results:"
> AI: "Job 1: Build a WordPress Website. Budget: 500 USD. Duration: 1-3 months. Workload: Not specified. Client rating: 4.5 out of 5."
> AI: "Job 2: React Frontend Developer Needed. Budget: 1000 USD. Duration: 1-4 weeks. Workload: More than 30 hrs/week. Client rating: 5 out of 5."
> AI: "Would you like me to search for a different category? Say stop to exit."
> User: "no thanks"
> AI: "Happy job hunting! Talk to you later."

## Important Notes

- This Ability uses the Upwork GraphQL API (`api.upwork.com/graphql/v2`)
- For full functionality, you need Upwork API credentials with appropriate permissions
- Jobs are limited to top 5 results to keep voice responses concise
- The ability includes error handling for API failures and provides user-friendly messages

## Technical Details

- API Used: Upwork GraphQL API v2
- Authentication: OAuth 2.0 (client credentials flow)
- Dependencies: `requests` library
- Pattern: API Template (Speak → Input → API Call → Speak Result → Exit)

## License

MIT License - See LICENSE file for details.
