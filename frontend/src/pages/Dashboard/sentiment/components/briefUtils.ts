// 工具函数 — 与 BriefRenderer 分离,以满足 react-refresh/only-export-components.

/** 从 yuqin brief Markdown body 提取 h2 锚点(`## 一、…` 等),供锚点目录使用. */
export function extractAnchors(body: string): { id: string; text: string }[] {
  const out: { id: string; text: string }[] = [];
  body.split('\n').forEach((line, idx) => {
    const m = line.match(/^##\s+(.+)$/);
    if (m) out.push({ id: `h2-${idx}`, text: m[1].trim() });
  });
  return out;
}
