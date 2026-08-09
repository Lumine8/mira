import { useEffect } from "react";

export type FaviconMode = "idle" | "typing" | "alert";

const ICONS: Record<FaviconMode, string> = {
  idle: "/favicon.svg",
  typing: "/favicon-typing.svg",
  alert: "/favicon-alert.svg",
};

function setFavicon(href: string) {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    link.type = "image/svg+xml";
    document.head.appendChild(link);
  }
  if (link.getAttribute("href") !== href) link.setAttribute("href", href);
}

/** Mirror Mira's state in the browser tab icon: her quiet glow at rest, a
 *  brighter/liveller one while she thinks, and a warm attention-glow when she
 *  has something to say. Higher priority wins when several are true. */
export function useFavicon(mode: FaviconMode) {
  useEffect(() => {
    const href = ICONS[mode] ?? ICONS.idle;
    setFavicon(href);
    return () => setFavicon(ICONS.idle);
  }, [mode]);
}