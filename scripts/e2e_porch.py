"""e2e_porch.py - verify the porch conversation (conv 327) end to end.

Starts a fresh porch for a scratch guest device, has a 3-exchange sitting, and
expects her closing + porch_ended after the third reply. Requires the API.

    python scripts/e2e_porch.py
"""

import asyncio
import json
import uuid

import httpx
import websockets

API = "http://localhost:8000"
WS = "ws://localhost:8000"


async def main() -> None:
    guest = f"e2e-porch-{uuid.uuid4()}"
    headers = {"X-Guest-Id": guest}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{API}/porch/start", headers=headers)
        resp.raise_for_status()
        body = resp.json()
    conv_id = body["conversation_id"]
    print(f"[porch {conv_id}] opening: {body['opening']!r}")

    ws_url = f"{WS}/ws/conversation/{conv_id}?guest={guest}"
    lines = [
        "the fireflies are late this year, aren't they",
        "do you come here often",
        "is there room for a seat",
    ]
    async with websockets.connect(ws_url) as ws:
        for turn, line in enumerate(lines, 1):
            await ws.send(json.dumps({"type": "text", "content": line}))
            got_reply = False
            got_closing = False
            is_last = turn == len(lines)
            async with asyncio.timeout(240):
                while True:
                    event = json.loads(await ws.recv())
                    if event.get("type") == "stream_token":
                        continue
                    if event.get("type") == "message":
                        print(f"  turn {turn} mira: {event.get('content')!r}")
                        got_reply = True
                        if not is_last:
                            break
                        continue  # the final reply is followed by her closing
                    if event.get("type") == "porch_ended":
                        print(f"  turn {turn} porch_ended: {event.get('closing')!r}")
                        got_closing = True
                        break
                    if event.get("type") == "error":
                        print(f"  [error] {event.get('message')}")
                        return
            if not got_reply:
                print(f"  ! turn {turn} got no reply")
                return
            if got_closing:
                print(f"  porch ended after {turn} exchanges — pass")
                # Idempotence: a second start must return the same ended porch
                async with httpx.AsyncClient(timeout=120.0) as client:
                    again = await client.post(f"{API}/porch/start", headers=headers)
                again_body = again.json()
                assert again_body["conversation_id"] == conv_id, "porch must be idempotent"
                assert again_body.get("ended") is True, "an ended porch stays ended"
                print("  resumed same porch id, still ended — pass")
                return
        print("  ! porch did not end after three exchanges")
        return
    print("  ! socket closed early")


if __name__ == "__main__":
    asyncio.run(main())
