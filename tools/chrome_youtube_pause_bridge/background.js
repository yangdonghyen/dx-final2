importScripts("config.js");

const pauseEndpoint = `${TRAVELMATE_API_BASE}/api/v1/discovery/youtube-pause`;

console.info("[TravelMate YouTube Bridge] service worker ready", pauseEndpoint);

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "youtube-pause") return;

  fetch(pauseEndpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.payload)
  })
    .then((response) => {
      if (!response.ok) {
        throw new Error(`TravelMate pause bridge returned HTTP ${response.status}`);
      }
      console.info(
        "[TravelMate YouTube Bridge] EVENT_SENT",
        response.status,
        message.payload.event_id,
        message.payload.video_id,
        message.payload.position_sec
      );
      sendResponse({ ok: true, status: response.status });
    })
    .catch((error) => {
      console.error("[TravelMate YouTube Bridge] EVENT_FAILED", pauseEndpoint, message.payload.event_id, String(error));
      sendResponse({ ok: false, error: String(error) });
    });

  return true;
});
