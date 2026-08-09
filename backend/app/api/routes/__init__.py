from fastapi import APIRouter, Depends

from app.api.routes import browser, calls, health, history, mira, tools, ws, x
from app.deps import require_access_token

api_router = APIRouter()
api_router.include_router(health.router)  # /health stays public (survivors)
api_router.include_router(calls.router, dependencies=[Depends(require_access_token)])
api_router.include_router(history.router, dependencies=[Depends(require_access_token)])
api_router.include_router(mira.router, dependencies=[Depends(require_access_token)])
api_router.include_router(tools.router, dependencies=[Depends(require_access_token)])
api_router.include_router(browser.router, dependencies=[Depends(require_access_token)])
api_router.include_router(ws.router)  # websockets authorize their own token
api_router.include_router(x.router)  # auth/callback is token-free (OAuth redirect)
