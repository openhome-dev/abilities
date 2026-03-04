# Flight Price Checker

![Community](https://img.shields.io/badge/OpenHome-Community-orange?style=flat-square)
![Author](https://img.shields.io/badge/Author-Reyad-lightgrey?style=flat-square)

## What It Does
Finds the cheapest real-time flight prices using Kiwi.com (via RapidAPI).  
Just say things like "Dhaka to Bangkok" or "from Dhaka to Chittagong" — it returns the top 3 cheapest options with airline and approximate duration.

## Suggested Trigger Words
- flight prices
- flight price
- cheap flight
- how much to fly
- flights to
- price of flight
- flight cost
- fly from
- from to
- flight information

## Setup
- Requires a **RapidAPI key** for the Kiwi.com Cheap Flights API (free tier available at https://rapidapi.com/emir12/api/kiwi-com-cheap-flights).
- Replace the placeholder `API_KEY` in `main.py` with your own key before using.

## How It Works
1. User triggers with "flight prices" (or similar)
2. Greets and asks for from/to cities
3. Parses simple phrases like "Dhaka to Bangkok"
4. Calls Kiwi API → returns top 3 cheapest flights
5. Offers more details on request
6. Say "stop" or "exit" to end

## Example Conversation
**User:** flight prices  
**AI:** Hi! I can check flight prices. Tell me where from and to...  

**User:** Dhaka to Bangkok  
**AI:** Understood — from Dhaka to Bangkok. Checking prices now...  
Cheapest flights: Option 1: $45 with US-Bangla Airlines, ~50 min. ... Want more details?  

**User:** yes  
**AI:** More info: Option 1: $45, 50 min, US-Bangla Airlines. Hand bag included...  

**User:** stop  
**AI:** Flight search finished. Safe travels!