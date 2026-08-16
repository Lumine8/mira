from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
import asyncio
import httpx

from app.services.identity import get_current_user_id
from app.services.tools.service import _page_to_text, _backup_text

router = APIRouter(tags=["mira"])

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
# A page becomes words before it reaches the panel; cap the reader at a size
# that stays readable without becoming an essay.
_READABLE_MAX_CHARS = 14_000


@router.get("/mira/browse/readable")
async def browse_readable(
    url: str,
    _: int = Depends(get_current_user_id),
) -> dict:
    """The page, reduced to what is actually readable — the same extraction the
    browse tool feeds Mira. Rendered in the panel as words instead of an
    iframe, so sites that refuse to be framed (X-Frame-Options, CSP) still show
    their content."""
    try:
        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": _UA},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            body = resp.text
    except httpx.HTTPStatusError as exc:
        backup = await asyncio.to_thread(_backup_text, url)
        return {
            "url": url,
            "title": "",
            "content": backup
            or f"[error] {exc.response.status_code} for {url} — the site refused the reader; use the link above to open it yourself",
        }
    except Exception as exc:  # noqa: BLE001
        backup = await asyncio.to_thread(_backup_text, url)
        return {
            "url": url,
            "title": "",
            "content": backup or f"[error] could not reach {url}: {exc}",
        }

    if "html" not in ctype and "text" not in ctype and "json" not in ctype:
        backup = await asyncio.to_thread(_backup_text, url)
        return {
            "url": url,
            "title": "",
            "content": backup or f"[refused] content-type not readable: {ctype}",
        }

    title = _extract_title(body) if "html" in ctype else url
    content = _page_to_text(body)
    if len(content) > _READABLE_MAX_CHARS:
        content = content[:_READABLE_MAX_CHARS] + "\n… (truncated)"
    return {"url": url, "title": title or url, "content": content or "[empty page]"}


def _extract_title(html: str) -> str:
    import re

    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:200]


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