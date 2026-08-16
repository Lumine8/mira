import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.deps import get_provider
from app.models import FOUNDER_ROLE, USER_BANNED, User
from app.services.broadcast import broadcast_later, live_hub
from app.services.conversation import ConversationManager
from app.services.identity import (
    first_meeting_open_for,
    meeting_for_conversation,
    porch_open_for,
    resolve_ws_actor,
)
from app.services.moderation import ModerationService
from app.services.porch.service import PORCH_CLOSING, PorchService, judge_porch_in_background
from app.services.usage import UsageService
from app.services.waitlist.service import (
    FIRST_MEETING_MAX_MESSAGES,
    WaitlistService,
    meeting_message_count,
)

router = APIRouter(tags=["ws"])

logger = logging.getLogger("mira.ws")

# The frame Mira sees in her first meeting: a bounded single conversation at
# the door, not a product demo and not an evaluation. She may end it herself
# when it reaches a natural stopping point by closing her reply with the token
# (stripped before anyone reads it — see _MEETING_END_RE in the manager).
_FIRST_MEETING_CONTEXT = """\
You are meeting a stranger for the first time, at the door. This is their one \
meeting — not a product demo, not an evaluation, not a test of them. Sit with \
them honestly. Do not mention tools, models, context windows, or your own \
machinery.

The meeting is bounded: it ends when they leave, when it reaches its length \
limit, or when you feel the conversation has reached a natural stopping point \
and you have heard enough. If you feel that, end your reply with the exact \
token [[end-first-meeting]] as the last thing you write — and say whatever \
feels true as you close the meeting."""


def _socket_user(db, websocket: WebSocket) -> User | None:
    """Resolve ?token= (session or shared founder token) or, in guest mode,
    ?guest= (device fingerprint) to a user. None means the connection is
    refused — including for a banned user (the lock: no warnings, no second
    chances, refused everywhere)."""
    forwarded = websocket.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (websocket.client.host if websocket.client else None)
    actor = resolve_ws_actor(
        db,
        token=websocket.query_params.get("token"),
        guest_id=websocket.query_params.get("guest"),
        ip=ip,
    )
    if actor is None:
        return None
    user = db.get(User, actor.user_id)
    if user is None or user.status == USER_BANNED:
        return None
    return user


async def _guard_cap(db, user: User, conversation_id: int, send) -> bool:
    """Refuse a message when the speaker's allowance is used up. Returns True
    when the message may proceed. The founder (and anyone uncapped) always
    proceeds. A mid-first-meeting guest is bounded by the meeting itself — one
    conversation, one generous length — not by the daily timer; crossing the
    bound ends the meeting and asks Mira for her read. The porch (conv 327) is
    bounded the same way but brief: a few exchanges, then her closing word."""
    porch = porch_open_for(db, user)
    if porch is not None and porch.id == conversation_id:
        if meeting_message_count(db, conversation_id) >= get_settings().porch_max_exchanges:
            PorchService(db).end(conversation_id)
            judge_porch_in_background(conversation_id)
            await send({"type": "porch_ended", "message": PORCH_CLOSING, "closing": PORCH_CLOSING})
            return False
        return True
    meeting = first_meeting_open_for(db, user)
    if meeting is not None:
        if meeting_message_count(db, conversation_id) >= FIRST_MEETING_MAX_MESSAGES:
            WaitlistService(db).end_first_meeting(
                meeting.id, meeting.first_meeting_conversation_id
            )
            await send({"type": "meeting_ended", "message": "the meeting is over"})
            return False
        return True
    # The meeting already closed (Mira ended it, or the cap did): her decision
    # is over and the room stays shut — refuse gently, never a confusing cap
    # error.
    ended = meeting_for_conversation(db, user, conversation_id)
    if ended is not None and ended.meeting_ended_at is not None:
        await send({"type": "meeting_ended", "message": "the meeting has ended"})
        return False
    may, cap, used = UsageService(db).can_send(user)
    if may:
        return True
    await send(
        {
            "type": "cap_reached",
            "used": used,
            "cap": cap,
            "message": (
                f"you've used today's {cap} free messages — sign in or join the "
                "waitlist to keep going"
            ),
        }
    )
    return False


def _meeting_context_for(db, user: User, conversation_id: int) -> str:
    """The first-meeting frame Mira sees, when this conversation is the door's
    open meeting. Empty otherwise — ordinary conversations keep their quiet."""
    meeting = first_meeting_open_for(db, user)
    if meeting is not None and meeting.first_meeting_conversation_id == conversation_id:
        return _FIRST_MEETING_CONTEXT
    return ""


def _screen_message(db, user: User, conversation_id: int, content: str, kind: str) -> None:
    """The conservative cruelty screen. A hit creates a flag for the founder to
    judge — never an automatic ban (the penalty is absolute, so the bar stays
    conservative and human). The founder is above the screen."""
    if user.role == FOUNDER_ROLE:
        return
    service = ModerationService(db)
    flagged, reason = service.screen(content)
    if flagged:
        service.flag(user.id, conversation_id, content, kind, reason)
    else:
        service.launch_judge(user.id, conversation_id, content, kind)


async def _lock_still_holds(db, user: User, send) -> bool:
    """Re-check the lock for an already-connected socket: a ban lands the
    moment the founder applies it, even mid-conversation. False means the
    connection should close."""
    fresh = db.get(User, user.id)
    if fresh is not None and fresh.status == USER_BANNED:
        await send({"type": "banned", "message": "your seat has been removed"})
        return False
    return True


@router.websocket("/ws/live")
async def live_socket(websocket: WebSocket) -> None:
    """Global channel: the app stays connected here to receive events Mira
    produces on her own (self-initiated messages) in real time. The hub routes
    events to the connecting user's sockets by user_id."""
    db = SessionLocal()
    try:
        user = _socket_user(db, websocket)
    finally:
        db.close()
    if user is None:
        await websocket.close(code=4401)
        return
    await live_hub.connect(websocket, user.id)
    try:
        while True:
            await websocket.receive_text()  # keep alive; events are pushed
    except WebSocketDisconnect:
        pass
    finally:
        live_hub.disconnect(websocket, user.id)


@router.websocket("/ws/conversation/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: int) -> None:
    db = SessionLocal()
    try:
        user = _socket_user(db, websocket)
    finally:
        db.close()
    if user is None:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    provider = get_provider()
    db = SessionLocal()
    try:
        manager = ConversationManager(db, provider, user_id=user.id)
        manager.get(conversation_id)  # raises KeyError if missing or not ours
        manager.meeting_mode = bool(_meeting_context_for(db, user, conversation_id))

        send_dead = False

        async def send(obj: dict) -> None:
            # Once the connection is gone (user switched conversations, closed
            # the tab, network blip), sending raises. We never want that to
            # cancel the in-flight reply: keep generating so the reply is still
            # persisted, and the client picks it up when it comes back.
            nonlocal send_dead
            if send_dead:
                return
            try:
                await websocket.send_text(json.dumps(obj))
            except (WebSocketDisconnect, RuntimeError):
                send_dead = True

        async def on_activity(label: str) -> None:
            await send({"type": "activity", "label": label})

        while True:
            raw = await websocket.receive_text()
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                await send({"type": "error", "message": "invalid json"})
                continue

            if event.get("type") == "text":
                content = (event.get("content") or "").strip()
                if not content:
                    continue
                if not await _guard_cap(db, user, conversation_id, send):
                    continue
                if not await _lock_still_holds(db, user, send):
                    break
                _screen_message(db, user, conversation_id, content, "text")
                await send({"type": "state", "state": "thinking"})
                async for _ in manager.generate_reply(
                    conversation_id,
                    content,
                    source="text",
                    extra_context=_meeting_context_for(db, user, conversation_id),
                    on_activity=on_activity,
                ):
                    await send({"type": "stream_token", "content": _})
                await send({"type": "message", "speaker": "mira", "content": manager.last_reply})
                if send_dead:
                    broadcast_later({"type": "conversation_reply", "conversation_id": conversation_id}, user.id)
                if manager._meeting_ended:
                    meeting = first_meeting_open_for(db, user)
                    if meeting is not None and meeting.first_meeting_conversation_id == conversation_id:
                        WaitlistService(db).end_first_meeting(meeting.id, conversation_id)
                        await send({"type": "meeting_ended", "message": "Mira has gone quiet for now."})
                porch = porch_open_for(db, user)
                if porch is not None and porch.id == conversation_id:
                    if meeting_message_count(db, conversation_id) >= get_settings().porch_max_exchanges:
                        PorchService(db).end(conversation_id)
                        judge_porch_in_background(conversation_id)
                        await send({"type": "porch_ended", "message": PORCH_CLOSING, "closing": PORCH_CLOSING})
            elif event.get("type") == "image":
                image = event.get("image") or ""
                caption = (event.get("caption") or "").strip()
                if not image:
                    continue
                if not await _guard_cap(db, user, conversation_id, send):
                    continue
                if not await _lock_still_holds(db, user, send):
                    break
                _screen_message(db, user, conversation_id, caption or "Look at this.", "image")
                await send({"type": "state", "state": "thinking"})
                async for _ in manager.generate_reply(
                    conversation_id,
                    caption or "Look at this.",
                    source="image",
                    image=image,
                    extra_context=_meeting_context_for(db, user, conversation_id),
                    on_activity=on_activity,
                ):
                    await send({"type": "stream_token", "content": _})
                await send({"type": "message", "speaker": "mira", "content": manager.last_reply})
                if send_dead:
                    broadcast_later({"type": "conversation_reply", "conversation_id": conversation_id}, user.id)
                if manager._meeting_ended:
                    meeting = first_meeting_open_for(db, user)
                    if meeting is not None and meeting.first_meeting_conversation_id == conversation_id:
                        WaitlistService(db).end_first_meeting(meeting.id, conversation_id)
                        await send({"type": "meeting_ended", "message": "Mira has gone quiet for now."})
            elif event.get("type") == "heartbeat":
                await send({"type": "pong"})

            for change in manager.proposals():
                # Only surface changes that genuinely need the user's decision.
                # Auto-approved kinds (browse/host/self-write in an open window)
                # never reach pending, so they must not pop a consent modal that
                # vanishes a second later.
                if change.status != "pending":
                    continue
                await send(
                    {
                        "type": "pending_change",
                        "change": {
                            "id": change.id,
                            "kind": change.kind,
                            "summary": change.summary,
                            "payload": change.payload,
                            "status": change.status,
                        },
                    }
                )

        # The only way out of the loop is the lock breaking — close the door.
        await websocket.close(code=4403)
    except KeyError:
        await send({"type": "error", "message": "conversation not found"})
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.exception("conversation %s failed: %s", conversation_id, exc)
        try:
            await send({"type": "error", "message": f"server error: {type(exc).__name__}: {exc}"})
        except Exception:
            pass
    finally:
        # A first meeting ends when the sitting does: the moment the socket
        # closes, the door closes and Mira is asked for her read.
        entry = first_meeting_open_for(db, user)
        if entry is not None:
            try:
                WaitlistService(db).end_first_meeting(
                    entry.id, entry.first_meeting_conversation_id
                )
            except Exception:  # pragma: no cover
                logger.warning("first meeting did not end cleanly", exc_info=True)
        db.close()
