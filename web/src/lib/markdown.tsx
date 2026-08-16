import type { ReactNode } from "react";

export function authorLabel(author: "founder" | "mira"): string {
  return author === "mira" ? "by Mira" : "given to Mira";
}

export function dateLabel(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

// ── a small markdown reader, enough to render her papers properly ────────

export function parseInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    const key = nodes.length;
    if (tok.startsWith("**")) nodes.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) nodes.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else nodes.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function splitPaper(content: string, fallbackTitle: string, author: "founder" | "mira") {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  let title = "";
  let rest = lines;
  if (lines.length > 0 && /^#\s+/.test(lines[0])) {
    title = lines[0].replace(/^#\s+/, "").trim();
    rest = lines.slice(1);
  }
  if (rest.length > 0 && /^\*[^*]+\*$/.test(rest[0].trim())) {
    rest = rest.slice(1);
  }
  return {
    title: title || fallbackTitle,
    byline: authorLabel(author),
    body: rest.join("\n").trim(),
  };
}

export function renderBlocks(text: string): ReactNode[] {
  const paragraphs = text.split(/\n{2,}/);
  const out: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;

  const flush = () => {
    if (!list) return;
    const key = out.length;
    const items = list.items.map((item, i) => (
      <li key={i}>{parseInline(item.replace(/^[-*]\s+/, "").replace(/^\d+\.\s+/, ""))}</li>
    ));
    out.push(list.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
    list = null;
  };

  for (const para of paragraphs) {
    const trimmed = para.trim();
    if (!trimmed) continue;

    if (/^#{1,4}\s+/.test(trimmed)) {
      flush();
      const level = trimmed.match(/^#+/)?.[0].length ?? 2;
      const Tag = (level <= 2 ? "h3" : level === 3 ? "h4" : "h5") as "h3" | "h4" | "h5";
      out.push(<Tag key={out.length}>{parseInline(trimmed.replace(/^#+\s+/, ""))}</Tag>);
      continue;
    }

    const lines = trimmed.split("\n");
    const isNumbered = lines.every((l) => /^\d+\.\s+/.test(l));
    const isBullet = lines.every((l) => /^[-*]\s+/.test(l) || /^\d+\.\s+/.test(l));
    if (isBullet && lines.length > 0) {
      if (!list || list.ordered !== isNumbered) flush();
      list = list && list.ordered === isNumbered ? list : { ordered: isNumbered, items: [] };
      list.items.push(...lines);
      continue;
    }

    flush();

    if (lines.every((l) => /^>\s?/.test(l))) {
      out.push(
        <blockquote key={out.length}>
          {parseInline(lines.map((l) => l.replace(/^>\s?/, "")).join(" "))}
        </blockquote>,
      );
      continue;
    }

    out.push(<p key={out.length}>{parseInline(trimmed)}</p>);
  }
  flush();
  return out;
}