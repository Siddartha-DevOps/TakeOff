"""
TakeOff.ai — Real-time collaboration: presence, live cursors, pinned
comments. Closes memory/TOGAL_PARITY_REAUDIT.md #16: "No real-time
collaboration (hardcoded avatars). Build: Liveblocks/Yjs presence, cursors,
comments."

Neither name in the gap is a drop-in here: Liveblocks is a paid external
SaaS needing an account + API key this sandbox has neither of; Yjs is a
CRDT for merging shared *documents*, and this app has no shared-document
state to merge (annotations are discrete DB rows). So this builds the same
capability directly on infrastructure already in CLAUDE.md's stack list:
a FastAPI WebSocket per project "room", fanned out through Redis pub/sub
(CLAUDE.md §3: "Cache/presence: Upstash Redis") so presence/cursor
broadcast works across more than one server process, not just one Python
object's in-memory state.

Two different consistency models, deliberately:
  - Presence/cursors are ephemeral — stored in Redis keys with a TTL
    (`presence:project:{id}:user:{uid}`, 60s), refreshed on every cursor
    update. If a browser tab dies without a clean WebSocket close (crash,
    force-quit), the stale presence entry simply expires within 60s rather
    than lingering forever — no explicit cleanup job needed, and no
    dependency on ever seeing a disconnect event.
  - Comments are durable — written straight to Postgres (models.Comment)
    before ever reaching Redis. Redis pub/sub only carries the live
    "something changed" notification; a client that was offline when a
    comment was created still sees it via the plain REST list endpoint on
    next load. Redis going away loses *live* updates, never data.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from fastapi import WebSocket

PRESENCE_TTL_SECONDS = 60
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_AVATAR_COLORS = ["#6366f1", "#8b5cf6", "#06b6d4", "#f97316", "#10b981", "#ec4899", "#eab308", "#ef4444"]


def color_for_user(user_id: int) -> str:
    return _AVATAR_COLORS[user_id % len(_AVATAR_COLORS)]


def _presence_key(project_id: int, user_id: int) -> str:
    return f"presence:project:{project_id}:user:{user_id}"


def _events_channel(project_id: int) -> str:
    return f"presence:project:{project_id}:events"


class PresenceHub:
    """
    One instance shared by the whole FastAPI process (see
    routes/realtime_routes.py's module-level `hub`). Local WebSocket
    connections are process-local by necessity (you can only .send_text() a
    socket your own process accepted) — Redis is what lets an event
    published by *this* process's handling of one user's action reach
    another process's connections for other users, so this still works
    correctly if the app is ever run behind more than one uvicorn worker.
    """

    def __init__(self, redis_url: str = REDIS_URL):
        self._redis_url = redis_url
        self._redis: Optional[aioredis.Redis] = None
        self._pubsub_task: Optional[asyncio.Task] = None
        self._local_sockets: dict[int, dict[int, WebSocket]] = {}  # project_id -> {user_id: ws}
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def _ensure_listener(self):
        if self._pubsub_task is not None and not self._pubsub_task.done():
            return
        redis = await self._get_redis()
        pubsub = redis.pubsub()
        await pubsub.psubscribe("presence:project:*:events")
        self._pubsub_task = asyncio.create_task(self._listen(pubsub))

    async def _listen(self, pubsub):
        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue
            channel = message["channel"]
            # "presence:project:{id}:events" -> id
            try:
                project_id = int(channel.split(":")[2])
            except (IndexError, ValueError):
                continue
            sockets = self._local_sockets.get(project_id, {})
            if not sockets:
                continue
            try:
                envelope = json.loads(message["data"])
            except json.JSONDecodeError:
                continue
            exclude_user_id = envelope.get("exclude_user_id")
            payload = json.dumps(envelope["event"])
            dead = []
            for user_id, ws in sockets.items():
                if user_id == exclude_user_id:
                    continue  # the acting user already knows their own action
                try:
                    await ws.send_text(payload)
                except Exception:
                    dead.append(user_id)
            for user_id in dead:
                sockets.pop(user_id, None)

    async def publish(self, project_id: int, event: dict, exclude_user_id: Optional[int] = None):
        """
        exclude_user_id skips delivering this event back to the acting
        user's own socket(s) — they already know they moved their cursor,
        joined, or created a comment (the REST call that triggered a
        comment event returns the definitive result directly); without
        this, every action would double-deliver to its own author via the
        Redis round-trip, which is confusing for a client to dedupe and
        serves no purpose.
        """
        redis = await self._get_redis()
        envelope = {"event": event, "exclude_user_id": exclude_user_id}
        await redis.publish(_events_channel(project_id), json.dumps(envelope))

    async def connect(self, project_id: int, user_id: int, websocket: WebSocket):
        await self._ensure_listener()
        async with self._lock:
            self._local_sockets.setdefault(project_id, {})[user_id] = websocket

    async def disconnect(self, project_id: int, user_id: int):
        async with self._lock:
            room = self._local_sockets.get(project_id)
            if room:
                room.pop(user_id, None)
        redis = await self._get_redis()
        await redis.delete(_presence_key(project_id, user_id))

    async def touch_presence(self, project_id: int, user_id: int, presence: dict):
        redis = await self._get_redis()
        await redis.set(_presence_key(project_id, user_id), json.dumps(presence), ex=PRESENCE_TTL_SECONDS)

    async def snapshot_presence(self, project_id: int) -> list[dict]:
        redis = await self._get_redis()
        pattern = f"presence:project:{project_id}:user:*"
        users = []
        async for key in redis.scan_iter(match=pattern):
            raw = await redis.get(key)
            if raw:
                users.append(json.loads(raw))
        return users


hub = PresenceHub()


def comment_to_dict(comment) -> dict:
    # display_name/is_guest let the frontend render "Jane Smith" vs.
    # "Alex (Guest)" without needing to know the author_id/guest_name split
    # itself — comment.author_id and comment.guest_name are mutually
    # exclusive (see models.Comment's docstring).
    is_guest = comment.author_id is None
    display_name = comment.guest_name if is_guest else (comment.author.full_name or comment.author.email if comment.author else None)
    return {
        "id": comment.id,
        "project_id": comment.project_id,
        "drawing_id": comment.drawing_id,
        "parent_id": comment.parent_id,
        "x": comment.x,
        "y": comment.y,
        "body": comment.body,
        "author_id": comment.author_id,
        "author_email": comment.author.email if comment.author else None,
        "guest_name": comment.guest_name,
        "is_guest": is_guest,
        "display_name": display_name,
        "resolved": comment.resolved,
        "resolved_by": comment.resolved_by,
        "resolved_at": comment.resolved_at.isoformat() if comment.resolved_at else None,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
    }
