# TravelMate YouTube Pause Bridge

This unpacked Chrome extension restores the PC sender for the existing
FastAPI-to-Flutter YouTube pause bridge.

```
YouTube pause -> content.js -> chrome.runtime.sendMessage -> background.js
  -> POST {TRAVELMATE_API_BASE}/api/v1/discovery/youtube-pause
  -> FastAPI WebSocket broadcast -> phone app Home dialog
```

## Server address

The backend address lives in `config.js` (`TRAVELMATE_API_BASE`, default
`http://192.168.219.122:8000`). If the backend moves to another computer,
change it there **and** add the same origin to `host_permissions` in
`manifest.json`, then press **Reload** on `chrome://extensions` and refresh open
YouTube tabs.

## Setup

1. On the backend computer, run exactly one FastAPI instance on port 8000 that
   the phone (via `adb reverse tcp:8000 tcp:8000`) and this PC both reach:
   `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`.
   Do not also run a `127.0.0.1:8000` instance: on Windows the loopback bind
   takes phone traffic while LAN traffic goes to the other process, and the two
   never share WebSocket clients.
2. Open `chrome://extensions`, enable **Developer mode**, choose **Load unpacked**,
   then select this directory. Disable the old `DX YouTube Bridge` extension.
3. Reload an open YouTube tab, sign in to TravelMate on the phone, and leave its
   Home screen open.
4. Pause a YouTube watch or Shorts video. The service worker console
   (`chrome://extensions` > **service worker**) logs `pause delivered 200`.

The endpoint has no authentication. Allow port 8000 only from the YouTube PC
on the private network (Windows Firewall remote-address rule); never expose it
to the internet.
