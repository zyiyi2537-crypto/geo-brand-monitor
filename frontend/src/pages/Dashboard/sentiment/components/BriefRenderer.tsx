// 轻量 Markdown 渲染 — 只支持 yuqin brief 的子集:# h1 / ## h2 / ## 一、二、… h2 锚点 / - 列表 / **bold** / [link](url) / 段落
// 不引入 react-markdown 是为了避免新依赖。如果未来要支持完整 GFM,可换成包。

import React from 'react';

// === 简易 inline 渲染:粗体 + 链接 ===
const TOKEN_RE = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|\([^)]*\))/g;
function renderInline(text: string): React.ReactNode[] {
  const parts = text.split(TOKEN_RE).filter(Boolean);
  return parts.map((p, i) => {
    if (/^\*\*[^*]+\*\*$/.test(p)) {
      return <strong key={i}>{p.slice(2, -2)}</strong>;
    }
    const linkM = p.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkM) {
      return (
        <a
          key={i}
          href={linkM[2]}
          target="_blank"
          rel="noreferrer"
          style={{ color: 'var(--accent-primary)', textDecoration: 'underline', textUnderlineOffset: 3 }}
        >
          {linkM[1]}
        </a>
      );
    }
    return <React.Fragment key={i}>{p}</React.Fragment>;
  });
}

interface Props {
  body: string;
  /** 限制行数,Tab 1 内联简报用 */
  maxLines?: number;
}

export function BriefRenderer({ body, maxLines }: Props) {
  let lines = body.split('\n');
  if (maxLines && lines.length > maxLines) {
    lines = lines.slice(0, maxLines);
  }

  const elements: React.ReactNode[] = [];
  let listBuf: string[] = [];

  const flushList = () => {
    if (listBuf.length) {
      elements.push(
        <ul key={`ul-${elements.length}`} className="list-disc list-outside ml-5 space-y-1 text-sm text-secondary my-2">
          {listBuf.map((it, i) => <li key={i}>{renderInline(it)}</li>)}
        </ul>
      );
      listBuf = [];
    }
  };

  lines.forEach((line, idx) => {
    const trimmed = line.trim();
    if (!trimmed) {
      flushList();
      return;
    }
    let m: RegExpMatchArray | null;
    if ((m = trimmed.match(/^#\s+(.+)$/))) {
      flushList();
      elements.push(
        <h1 key={idx} className="text-xl sm:text-2xl font-bold text-primary mt-2 mb-3">
          {renderInline(m[1])}
        </h1>
      );
    } else if ((m = trimmed.match(/^##\s+(.+)$/))) {
      flushList();
      elements.push(
        <h2
          key={idx}
          id={`h2-${idx}`}
          className="text-base sm:text-lg font-semibold text-primary mt-5 mb-2"
          style={{ scrollMarginTop: 80 }}
        >
          {renderInline(m[1])}
        </h2>
      );
    } else if ((m = trimmed.match(/^###\s+(.+)$/))) {
      flushList();
      elements.push(
        <h3 key={idx} className="text-sm font-semibold text-primary mt-3 mb-1">
          {renderInline(m[1])}
        </h3>
      );
    } else if ((m = trimmed.match(/^-\s+(.+)$/))) {
      listBuf.push(m[1]);
    } else if ((m = trimmed.match(/^\d+\.\s+(.+)$/))) {
      listBuf.push(m[1]);
    } else {
      flushList();
      elements.push(
        <p key={idx} className="text-sm text-secondary leading-relaxed my-2">
          {renderInline(trimmed)}
        </p>
      );
    }
  });
  flushList();

  return <div className="brief-content">{elements}</div>;
}
