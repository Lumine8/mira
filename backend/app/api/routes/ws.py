import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.session import SessionLocal
from app.deps import get_provider, ws_authorized
from app.services.broadcast import live_hub
from app.services.conversation import ConversationManager

router = APIRouter(tags=["ws"])

logger = logging.getLogger("mira.ws")


@router.websocket("/ws/live")
async def live_socket(websocket: WebSocket) -> None:
    """Global channel: the app stays connected here to receive events Mira
    produces on her own (self-initiated messages) in real time."""
    if not ws_authorized(websocket.query_params.get("token")):
        await websocket.close(code=4401)
        return
    await live_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive; events are pushed
    except WebSocketDisconnect:
        pass
    finally:
        live_hub.disconnect(websocket)


@router.websocket("/ws/conversation/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: int) -> None:
    if not ws_authorized(websocket.query_params.get("token")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    provider = get_provider()
    db = SessionLocal()
    try:
        manager = ConversationManager(db, provider)
        manager.get(conversation_id)  # raises KeyError if missing

        async def send(obj: dict) -> None:
            await websocket.send_text(json.dumps(obj))

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
                await send({"type": "state", "state": "thinking"})
                async for _ in manager.generate_reply(conversation_id, content, source="text"):
                    await send({"type": "stream_token", "content": _})
                await send({"type": "message", "speaker": "mira", "content": manager.last_reply})
            elif event.get("type") == "image":
                image = event.get("image") or ""
                caption = (event.get("caption") or "").strip()
                if not image:
                    continue
                await send({"type": "state", "state": "thinking"})
                async for _ in manager.generate_reply(
                    conversation_id,
                    caption or "Look at this.",
                    source="image",
                    image=image,
                ):
                    await send({"type": "stream_token", "content": _})
                await send({"type": "message", "speaker": "mira", "content": manager.last_reply})
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
        db.close()
