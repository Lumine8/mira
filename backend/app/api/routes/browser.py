from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
import httpx

from app.services.identity import get_current_user_id

router = APIRouter(tags=["mira"])

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


@router.get("/mira/browse/view", response_class=HTMLResponse)
async def browse_view(
    url: str,
    depth: int = 0,
    _: int = Depends(get_current_user_id),
) -> HTMLResponse:
    """The mini-browser panel: renders a page inside the app. Loaded in an
    iframe, so it authenticates through the ``?token=`` query param (session or
    founder token) rather than a header."""
    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": _UA},
    ) as client:
        resp = await client.get(url)
        html = resp.text
    for header in ("X-Frame-Options", "Content-Security-Policy"):
        html = html.replace(header + ":", "X-Disabled-" + header + ":")
    # Anchor relative links/assets at the real page so they load from the
    # original site instead of this proxy route.
    base = _inject_base(html, url)
    # Always replace nested iframes with a plain placeholder: a page rendered
    # inside this one frame must not spawn its own browser frames (embeds,
    # ads), and it must not recurse back into this route through the proxy.
    base = _strip_iframes(base)
    # Some sites inject their own iframes AFTER load via JavaScript (verification
    # shells, ad widgets). Those escape the server-side strip above, so neutralise
    # them client-side: any iframe created at runtime is replaced on the spot.
    base = _inject_frame_buster(base)
    return HTMLResponse(base)


def _inject_base(html: str, url: str) -> str:
    import re

    if re.search(r"<base\s", html, re.IGNORECASE):
        return html
    parsed = httpx.URL(url)
    base = f"{parsed.scheme}://{parsed.host}"
    head = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if not head:
        return html
    return html[: head.end()] + f'<base href="{base}/">' + html[head.end():]


def _strip_iframes(html: str) -> str:
    import re

    return re.sub(
        r"<iframe\b[^>]*>.*?</iframe>",
        "<div style=\"padding:10px;color:#888;font-family:sans-serif;font-size:12px\">embedded frame hidden</div>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _inject_frame_buster(html: str) -> str:
    """Neutralise iframes a page creates at runtime (JS-injected verification
    shells, ad widgets) so the panel never shows a nested browser inside the
    browser. Any iframe appearing after load is removed immediately; the rest of
    the page is left untouched."""
    guard = (
        "<script>(function(){var s=document.createElement('style');"
        "s.textContent='iframe{display:none!important}';"
        "(document.head||document.documentElement).appendChild(s);"
        "var kill=function(r){var l=(r||document).querySelectorAll('iframe');"
        "for(var i=0;i<l.length;i++){var f=l[i];try{f.parentNode.removeChild(f)}catch(e){}}};"
        "new MutationObserver(function(ms){ms.forEach(function(m){if(m.type==='childList')kill(m.target)})})"
        ".observe(document.documentElement,{childList:true,subtree:true});"
        "kill(document);})();</script></head>"
    )
    if "</head>" in html.lower():
        return html.replace("</head>", guard, 1)
    return guard.rstrip("</head>") + "</head>" + html
