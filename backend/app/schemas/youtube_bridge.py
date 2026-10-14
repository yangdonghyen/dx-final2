from pydantic import BaseModel


class YouTubePauseEvent(BaseModel):
    event: str
    video_id: str
    position_sec: int
    page_url: str | None = None
    # Sent by extension 1.1+; older senders omit them and the server fills one in.
    event_id: str | None = None
    detected_at: str | None = None
