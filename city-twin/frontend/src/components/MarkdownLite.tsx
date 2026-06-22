import type { ReactNode } from "react";

/**
 * Minimal, dependency-free, XSS-safe markdown renderer for the assistant's
 * message text. Returns React nodes (never raw HTML). Supports the subset LLMs
 * actually emit: #/##/### headings, `-`/`*`/`•` bullet lists, `1.` numbered
 * lists, **bold**, *italic*, and `inline code`.
 */

function inline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const re = /(\*\*([^*]+)\*\*|__([^_]+)__|\*([^*\n]+)\*|`([^`]+)`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const bold = m[2] ?? m[3];
    const italic = m[4];
    const code = m[5];
    if (bold != null) {
      nodes.push(
        <strong key={`${keyBase}-b${i}`} className="font-semibold text-text-primary">{bold}</strong>,
      );
    } else if (italic != null) {
      nodes.push(<em key={`${keyBase}-i${i}`}>{italic}</em>);
    } else if (code != null) {
      nodes.push(
        <code
          key={`${keyBase}-c${i}`}
          className="font-mono text-[0.9em] px-1 py-px bg-bg-primary/70 text-text-code rounded"
        >
          {code}
        </code>,
      );
    }
    last = m.index + m[0].length;
    i++;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export default function MarkdownLite({ text }: { text: string }) {
  const lines = (text ?? "").replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  const isBullet = (l: string) => /^\s*[-*•]\s+/.test(l);
  const isNumber = (l: string) => /^\s*\d+[.)]\s+/.test(l);
  const isHeading = (l: string) => /^#{1,3}\s+/.test(l);

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }

    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const lvl = h[1].length;
      const cls =
        lvl === 1 ? "text-[1.05em] font-semibold" : lvl === 2 ? "text-[1em] font-semibold" : "text-[0.95em] font-medium";
      blocks.push(
        <div key={key++} className={`${cls} text-text-primary mt-1`}>{inline(h[2], `h${key}`)}</div>,
      );
      i++;
      continue;
    }

    if (isBullet(line)) {
      const items: string[] = [];
      while (i < lines.length && isBullet(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*•]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++} className="space-y-0.5 my-0.5">
          {items.map((it, j) => (
            <li key={j} className="flex gap-1.5">
              <span className="text-accent-blue shrink-0 leading-relaxed">•</span>
              <span className="leading-relaxed">{inline(it, `ul${key}-${j}`)}</span>
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    if (isNumber(line)) {
      const items: string[] = [];
      while (i < lines.length && isNumber(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i++;
      }
      blocks.push(
        <ol key={key++} className="space-y-0.5 my-0.5">
          {items.map((it, j) => (
            <li key={j} className="flex gap-1.5">
              <span className="text-accent-blue shrink-0 font-mono leading-relaxed">{j + 1}.</span>
              <span className="leading-relaxed">{inline(it, `ol${key}-${j}`)}</span>
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !isHeading(lines[i]) &&
      !isBullet(lines[i]) &&
      !isNumber(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="leading-relaxed">{inline(para.join(" "), `p${key}`)}</p>,
    );
  }

  return <div className="space-y-1.5">{blocks}</div>;
}
