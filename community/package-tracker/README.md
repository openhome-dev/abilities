\# Package Tracker for OpenHome



A voice‑driven Package Tracker Ability for OpenHome.  

Users can add, list, check status, and remove packages using simple voice commands.



\## Setup

1\. Get a free API key from \[TrackingMore](https://www.trackingmore.com).

2\. Place your key in `config.json`:

&nbsp;  ```json

&nbsp;  {

&nbsp;    "trackingmore\_api\_key": "YOUR\_API\_KEY\_HERE"

&nbsp;  }


## Usage Examples

- **Add a package**  
  *User:* "Add package 92612903029511573030094547"  
  *Assistant:* Asks for a friendly name, then confirms.

- **List all packages**  
  *User:* "List my packages"  
  *Assistant:* Reads back all tracked packages with their names and numbers.

- **Check package status**  
  *User:* "Where's my package?" or "Check status for my Amazon order"  
  *Assistant:* Tells you the latest tracking info (e.g., "In transit, expected Friday").

- **Remove a package**  
  *User:* "Remove package 92612903029511573030094547" or "Remove my Amazon order"  
  *Assistant:* Asks "Are you sure?" – if you say yes, it's removed.

