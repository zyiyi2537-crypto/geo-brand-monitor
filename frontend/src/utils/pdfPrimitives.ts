// Shared primitives for PDF report generation. The default 25-category
// exporter (exportPdfReport.ts) and the 6 advanced-mode exporters
// (exportAdvancedPdfReport.ts) both build a list of HTML "blocks" and
// hand them to composeAndSavePdf, which captures, paginates, decorates
// with header/footer, and saves.

import jsPDF from 'jspdf';
import html2canvas from 'html2canvas';
import type { TFunction } from 'i18next';

// ----- Page geometry (A4 portrait, pt) -----
export const PAGE_W_PT = 595.28;
export const PAGE_H_PT = 841.89;
export const MARGIN_X_PT = 40;
export const HEADER_H_PT = 44;
export const FOOTER_H_PT = 30;
export const CONTENT_TOP_PT = HEADER_H_PT;
export const CONTENT_BOTTOM_PT = PAGE_H_PT - FOOTER_H_PT;
export const CONTENT_W_PT = PAGE_W_PT - 2 * MARGIN_X_PT;
export const CONTENT_H_PT = CONTENT_BOTTOM_PT - CONTENT_TOP_PT;
export const BLOCK_GAP_PT = 6;

// Offscreen container width in CSS px. 1pt ≈ 1.333 px @ 96dpi → 515pt × 1.333 ≈ 687 px.
export const CONTENT_W_PX = 690;
export const CANVAS_SCALE = 2;

export const STATUS_COLOR: Record<string, { bg: string; fg: string; key: 'pass' | 'warn' | 'fail' | 'info' }> = {
  PASS: { bg: '#dcfce7', fg: '#166534', key: 'pass' },
  WARN: { bg: '#fef3c7', fg: '#92400e', key: 'warn' },
  FAIL: { bg: '#fee2e2', fg: '#991b1b', key: 'fail' },
  INFO: { bg: '#dbeafe', fg: '#1e40af', key: 'info' },
};

export const FONT_STACK = `-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Helvetica Neue',Arial,sans-serif`;

export const escapeHtml = (s: string | number | null | undefined): string =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

export const blockWrapOpen = (extra = ''): string =>
  `<div data-pdf-block style="font-family:${FONT_STACK};color:#0f172a;background:#fff;width:${CONTENT_W_PX}px;box-sizing:border-box;${extra}">`;
export const blockWrapClose = `</div>`;

export const statusBadge = (status: string, t: TFunction): string => {
  const color = STATUS_COLOR[status] || STATUS_COLOR.INFO;
  const label = t(`result.pdfReport.statusLabels.${color.key}`);
  return `<span style="font-size:12px;font-weight:700;color:${color.fg};">${escapeHtml(label)}</span>`;
};

// ---------- Capture & pagination pipeline ----------

export type CapturedBlock = {
  dataUrl: string;
  widthPx: number;
  heightPx: number;
  widthPt: number;
  heightPt: number;
};

export const captureBlocks = async (htmlBlocks: string[]): Promise<CapturedBlock[]> => {
  const container = document.createElement('div');
  container.setAttribute('aria-hidden', 'true');
  container.style.cssText = `position:fixed;left:-10000px;top:0;width:${CONTENT_W_PX}px;background:#fff;z-index:-1;`;
  container.innerHTML = htmlBlocks.join('');
  document.body.appendChild(container);

  try {
    await new Promise((r) => setTimeout(r, 60));
    const nodes = Array.from(container.querySelectorAll('[data-pdf-block]')) as HTMLElement[];
    const captured: CapturedBlock[] = [];
    for (const node of nodes) {
      const canvas = await html2canvas(node, {
        scale: CANVAS_SCALE,
        backgroundColor: '#ffffff',
        useCORS: true,
        logging: false,
        windowWidth: CONTENT_W_PX,
      });
      const widthPx = canvas.width;
      const heightPx = canvas.height;
      const widthPt = CONTENT_W_PT;
      const heightPt = (heightPx * CONTENT_W_PT) / widthPx;
      captured.push({
        dataUrl: canvas.toDataURL('image/jpeg', 0.92),
        widthPx,
        heightPx,
        widthPt,
        heightPt,
      });
    }
    return captured;
  } finally {
    document.body.removeChild(container);
  }
};

export const sliceOversizedBlock = async (block: CapturedBlock): Promise<CapturedBlock[]> => {
  const pxPerPt = block.widthPx / block.widthPt;
  const maxChunkPx = Math.floor(CONTENT_H_PT * pxPerPt);
  if (block.heightPx <= maxChunkPx) return [block];

  const img = await new Promise<HTMLImageElement>((res, rej) => {
    const im = new Image();
    im.onload = () => res(im);
    im.onerror = rej;
    im.src = block.dataUrl;
  });

  const chunks: CapturedBlock[] = [];
  let y = 0;
  while (y < block.heightPx) {
    const chunkHeightPx = Math.min(maxChunkPx, block.heightPx - y);
    const c = document.createElement('canvas');
    c.width = block.widthPx;
    c.height = chunkHeightPx;
    const ctx = c.getContext('2d');
    if (!ctx) throw new Error('Canvas 2D context unavailable');
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(img, 0, -y);
    chunks.push({
      dataUrl: c.toDataURL('image/jpeg', 0.92),
      widthPx: c.width,
      heightPx: c.height,
      widthPt: CONTENT_W_PT,
      heightPt: (chunkHeightPx * CONTENT_W_PT) / block.widthPx,
    });
    y += chunkHeightPx;
  }
  return chunks;
};

export type PlacedBlock = { block: CapturedBlock; x: number; y: number; pageIndex: number };

export const packBlocks = (blocks: CapturedBlock[]): { placed: PlacedBlock[]; pageCount: number } => {
  const placed: PlacedBlock[] = [];
  let pageIndex = 0;
  let cursorY = CONTENT_TOP_PT;
  for (const b of blocks) {
    if (cursorY + b.heightPt > CONTENT_BOTTOM_PT && cursorY > CONTENT_TOP_PT) {
      pageIndex += 1;
      cursorY = CONTENT_TOP_PT;
    }
    if (b.heightPt > CONTENT_H_PT) {
      placed.push({ block: b, x: MARGIN_X_PT, y: cursorY, pageIndex });
      pageIndex += 1;
      cursorY = CONTENT_TOP_PT;
      continue;
    }
    placed.push({ block: b, x: MARGIN_X_PT, y: cursorY, pageIndex });
    cursorY += b.heightPt + BLOCK_GAP_PT;
  }
  return { placed, pageCount: pageIndex + 1 };
};

// ---------- Header/footer + entry point ----------

export interface StandardHeaderFooterOptions {
  rightHeaderText: string;
  t: TFunction;
}

// Capture a small HTML snippet to a data-URL image via html2canvas.
// Used for header/footer so CJK text renders correctly (jsPDF built-in
// fonts don't support Chinese characters).
const captureHtmlToImage = async (
  html: string,
  widthPx: number,
): Promise<{ dataUrl: string; widthPx: number; heightPx: number }> => {
  const container = document.createElement('div');
  container.setAttribute('aria-hidden', 'true');
  container.style.cssText = `position:fixed;left:-10000px;top:0;width:${widthPx}px;background:#fff;z-index:-1;`;
  container.innerHTML = html;
  document.body.appendChild(container);
  try {
    await new Promise((r) => setTimeout(r, 20));
    const canvas = await html2canvas(container, {
      scale: CANVAS_SCALE,
      backgroundColor: '#ffffff',
      useCORS: true,
      logging: false,
      windowWidth: widthPx,
    });
    return {
      dataUrl: canvas.toDataURL('image/png'),
      widthPx: canvas.width,
      heightPx: canvas.height,
    };
  } finally {
    document.body.removeChild(container);
  }
};

// Pre-render all per-page header/footer images so CJK text works.
//
// IMPORTANT:页眉页脚的左右文字必须同 baseline。HTML 里 Latin-only "Vigilath"
// 跟 CJK-mixed 右文(包含中文)在 html2canvas 下会被算成两套 line-box,基线差几 px,
// 哪怕都用 vertical-align:middle 也对不齐。唯一可靠做法:整条做成单个 SVG,
// 两个 <text> 节点 y 坐标完全一致(SVG 的 y 就是 baseline,deterministic)。
const renderHeaderFooterImages = async (
  opts: StandardHeaderFooterOptions,
  totalPages: number,
): Promise<{ headers: string[]; footers: string[] }> => {
  const { rightHeaderText, t } = opts;
  const year = new Date().getFullYear();
  const widthPx = CONTENT_W_PX;

  // SVG headers/footers — Latin+CJK text 同 baseline,无需理会 line-box 偏移
  const HDR_FONT = `'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Helvetica Neue',Arial,sans-serif`;
  const headerHtml =
    `<div style="width:${widthPx}px;background:#fff;">` +
    `<svg width="${widthPx}" height="22" xmlns="http://www.w3.org/2000/svg" font-family="${HDR_FONT}">` +
    `<text x="0" y="14" font-size="11" font-weight="600" fill="#78788c">Vigilath</text>` +
    `<text x="${widthPx}" y="14" text-anchor="end" font-size="11" fill="#78788c">${escapeHtml(rightHeaderText)}</text>` +
    `<line x1="0" y1="21" x2="${widthPx}" y2="21" stroke="#e2e8f0" stroke-width="1"/>` +
    `</svg></div>`;
  const headerImg = await captureHtmlToImage(headerHtml, widthPx);
  const headerDataUrl = headerImg.dataUrl;

  const footers: string[] = [];
  for (let p = 1; p <= totalPages; p++) {
    const pageText = t('result.pdfReport.pageOf', { current: p, total: totalPages });
    const footerHtml =
      `<div style="width:${widthPx}px;background:#fff;">` +
      `<svg width="${widthPx}" height="22" xmlns="http://www.w3.org/2000/svg" font-family="${HDR_FONT}">` +
      `<line x1="0" y1="1" x2="${widthPx}" y2="1" stroke="#e2e8f0" stroke-width="1"/>` +
      `<text x="0" y="15" font-size="10" fill="#94a3b8">Vigilath · © ${year}</text>` +
      `<text x="${widthPx}" y="15" text-anchor="end" font-size="10" fill="#94a3b8">${escapeHtml(pageText)}</text>` +
      `</svg></div>`;
    const footerImg = await captureHtmlToImage(footerHtml, widthPx);
    footers.push(footerImg.dataUrl);
  }

  const headers = Array(totalPages).fill(headerDataUrl) as string[];
  return { headers, footers };
};

export async function composeAndSavePdf(
  htmlBlocks: string[],
  headerFooterOpts: StandardHeaderFooterOptions,
  fileName: string,
): Promise<void> {
  const rawCaptured = await captureBlocks(htmlBlocks);

  const captured: CapturedBlock[] = [];
  for (const b of rawCaptured) {
    if (b.heightPt > CONTENT_H_PT) {
      const sliced = await sliceOversizedBlock(b);
      captured.push(...sliced);
    } else {
      captured.push(b);
    }
  }

  const { placed, pageCount } = packBlocks(captured);

  // Pre-render header/footer as images (supports CJK text).
  const { headers, footers } = await renderHeaderFooterImages(headerFooterOpts, pageCount);

  const pdf = new jsPDF({ unit: 'pt', format: 'a4', orientation: 'portrait' });

  const hdrWidthPt = CONTENT_W_PT;
  const hdrHeightPt = HEADER_H_PT - 4;
  const ftrWidthPt = CONTENT_W_PT;
  const ftrHeightPt = FOOTER_H_PT - 4;

  for (let p = 0; p < pageCount; p++) {
    if (p > 0) pdf.addPage();
    // Draw header image
    pdf.addImage(headers[p], 'PNG', MARGIN_X_PT, 6, hdrWidthPt, hdrHeightPt);
    // Draw footer image
    pdf.addImage(footers[p], 'PNG', MARGIN_X_PT, PAGE_H_PT - FOOTER_H_PT + 2, ftrWidthPt, ftrHeightPt);
    // Draw content blocks
    for (const item of placed) {
      if (item.pageIndex !== p) continue;
      pdf.addImage(
        item.block.dataUrl,
        'JPEG',
        item.x,
        item.y,
        item.block.widthPt,
        item.block.heightPt,
      );
    }
  }

  pdf.save(fileName);
}
