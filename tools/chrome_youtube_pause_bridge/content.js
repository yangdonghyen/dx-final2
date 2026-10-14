(() => {
  "use strict";

  const LOG = "[TravelMate YouTube Bridge]";
  // A second pause of the same video at (almost) the same position within
  // this window, without playback in between, is the same user pause
  // (YouTube can fire `pause` twice).
  const DUPLICATE_WINDOW_MS = 3000;
  // YouTube pauses the old video while it swaps to the next one in its SPA;
  // pauses this soon after a navigation starts are not user pauses.
  const NAVIGATION_GRACE_MS = 1500;

  let lastSent = null; // { videoId, position, at }
  let playedSinceLastSent = true;
  let navigatingUntil = 0;

  function videoIdFromUrl(url) {
    try {
      const parsed = new URL(url);
      if (parsed.pathname === "/watch") return parsed.searchParams.get("v");
      const shortsMatch = parsed.pathname.match(/^\/shorts\/([^/?]+)/);
      return shortsMatch ? shortsMatch[1] : null;
    } catch (_) {
      return null;
    }
  }

  function isAdPlaying(video) {
    const player = video.closest(".html5-video-player") || document.querySelector("#movie_player");
    return Boolean(player && (player.classList.contains("ad-showing") || player.classList.contains("ad-interrupting")));
  }

  function newEventId() {
    try {
      return crypto.randomUUID();
    } catch (_) {
      return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
  }

  // SPA navigation inside YouTube (next video, Shorts swipe, home -> watch).
  document.addEventListener("yt-navigate-start", () => {
    navigatingUntil = Date.now() + NAVIGATION_GRACE_MS;
  }, true);

  document.addEventListener("play", (event) => {
    if (event.target instanceof HTMLVideoElement) playedSinceLastSent = true;
  }, true);

  document.addEventListener(
    "pause",
    (event) => {
      const video = event.target;
      if (!(video instanceof HTMLVideoElement)) return;

      const videoId = videoIdFromUrl(window.location.href);
      if (!videoId) return;

      const position = Math.max(0, Math.floor(video.currentTime || 0));
      const skip = (reason) => console.info(LOG, "PAUSE_SKIPPED", reason, videoId, position);

      if (video.ended) return skip("video_ended");
      if (isAdPlaying(video)) return skip("ad");
      if (Date.now() < navigatingUntil) return skip("navigation");
      const now = Date.now();
      if (
        lastSent && lastSent.videoId === videoId && !playedSinceLastSent &&
        Math.abs(lastSent.position - position) <= 1 && now - lastSent.at < DUPLICATE_WINDOW_MS
      ) {
        return skip("duplicate");
      }

      const payload = {
        event: "pause",
        video_id: videoId,
        position_sec: position,
        page_url: window.location.href,
        event_id: newEventId(),
        detected_at: new Date(now).toISOString()
      };
      lastSent = { videoId, position, at: now };
      playedSinceLastSent = false;
      console.info(LOG, "PAUSE_DETECTED", payload.event_id, videoId, position);

      try {
        if (!chrome.runtime?.id) throw new Error("extension context invalidated");
        chrome.runtime.sendMessage({ type: "youtube-pause", payload }, (result) => {
          if (chrome.runtime.lastError) {
            console.warn(LOG, "EVENT_FAILED", payload.event_id, chrome.runtime.lastError.message);
          } else if (!result?.ok) {
            console.warn(LOG, "EVENT_FAILED", payload.event_id, result?.error);
          } else {
            console.info(LOG, "EVENT_SENT", payload.event_id, result.status);
          }
        });
      } catch (error) {
        // After the extension is reloaded, already-open tabs must be refreshed.
        console.warn(LOG, "EVENT_FAILED", payload.event_id, "reload this YouTube tab:", String(error));
      }
    },
    true
  );
})();
