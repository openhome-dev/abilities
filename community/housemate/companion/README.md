# HouseMate companion dashboard

1. `pip install flask flask-cors`
2. `python companion/app.py`
3. Set `DASHBOARD_URL = "http://YOUR_LAN_IP:8080"` in `main.py` (or your public tunnel URL)
4. Open `http://localhost:8080`

The Ability POSTs fire-and-forget snapshots to `/api/housemate/<event>`.
