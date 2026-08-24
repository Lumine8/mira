from fastapi import APIRouter

from app.api.routes import (
    abuse,
    audit,
    auth,
    billing,
    browser,
    calls,
    documents,
    health,
    history,
    mira,
    moderation,
    mote,
    porch,
    reminders,
    secret,
    skills,
    speech,
    system,
    toasts,
    tools,
    waitlist,
    ws,
    x,
)

api_router = APIRouter()
# Per-user routers authenticate per-endpoint via get_current_user_id (session
# bearer token, or the shared founder token). /health stays public. WebSockets
# and the X OAuth callback authorize themselves.
api_router.include_router(health.router)
api_router.include_router(audit.router)
api_router.include_router(auth.router)
api_router.include_router(calls.router)
api_router.include_router(history.router)
api_router.include_router(mira.router)
api_router.include_router(moderation.router)
api_router.include_router(mote.router)
api_router.include_router(reminders.router)
api_router.include_router(skills.router)
api_router.include_router(speech.router)
api_router.include_router(documents.router)
api_router.include_router(tools.router)
api_router.include_router(browser.router)
api_router.include_router(ws.router)  # websockets authorize their own token
api_router.include_router(x.router)  # auth/callback is token-free (OAuth redirect)
api_router.include_router(waitlist.router)
api_router.include_router(porch.router)  # public: a device at the door
api_router.include_router(secret.router)  # public: the pass-phrase is the key
api_router.include_router(system.router)  # host telemetry: the machine's live read
api_router.include_router(toasts.router)  # host toasts: the companion-free reach-out
api_router.include_router(abuse.router)
api_router.include_router(billing.router)
