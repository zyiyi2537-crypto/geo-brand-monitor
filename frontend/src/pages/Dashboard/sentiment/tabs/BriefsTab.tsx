import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import html2canvas from 'html2canvas';
import jsPDF from 'jspdf';

import { mockBriefs } from '../../../../mocks/sentiment';
import { useBriefs, useBriefDetail, usePosts } from '../../../../hooks/useSentiment';
import type { Brief, BriefSummary, SentimentAccount, SentimentPost } from '../../../../types/sentiment';

import { BriefRenderer } from '../components/BriefRenderer';
import { extractAnchors } from '../components/briefUtils';

// PDF 数据摘要计算 — 把 posts[] 聚合成 PDF 头/尾要展示的统计.
// 抽出来便于单测,且解耦于 React 渲染.
interface PdfDataSummary {
  totalPosts: number;
  sourceBreakdown: Array<{ source: string; count: number }>;
  sentimentBreakdown: { bullish: number; bearish: number; neutral: number; mixed: number; unknown: number };
  highRisk: SentimentPost[];      // top 5 high-risk
  timeRange: { earliest: string | null; latest: string | null };
}

function computeSummary(posts: SentimentPost[]): PdfDataSummary {
  const sourceMap = new Map<string, number>();
  const sentiment = { bullish: 0, bearish: 0, neutral: 0, mixed: 0, unknown: 0 };
  let earliest: string | null = null;
  let latest: string | null = null;
  const highRisk: SentimentPost[] = [];

  for (const p of posts) {
    const src = p.source || 'unknown';
    sourceMap.set(src, (sourceMap.get(src) || 0) + 1);
    const lbl = (p.sentiment_label || 'unknown') as keyof typeof sentiment;
    if (lbl in sentiment) sentiment[lbl] += 1;
    else sentiment.unknown += 1;
    if (p.publish_time) {
      if (!earliest || p.publish_time < earliest) earliest = p.publish_time;
      if (!latest || p.publish_time > latest) latest = p.publish_time;
    }
    if (p.risk_level === 'high') highRisk.push(p);
  }
  highRisk.sort((a, b) => (b.influence_potential || 0) - (a.influence_potential || 0));

  return {
    totalPosts: posts.length,
    sourceBreakdown: Array.from(sourceMap.entries())
      .map(([source, count]) => ({ source, count }))
      .sort((a, b) => b.count - a.count),
    sentimentBreakdown: sentiment,
    highRisk: highRisk.slice(0, 5),
    timeRange: { earliest, latest },
  };
}

// 数据来源中文名映射 — 让 PDF 不出现"eastmoney_ann"这种内部名
const SOURCE_LABEL: Record<string, string> = {
  eastmoney: '东方财富股吧',
  eastmoney_news: '东财资讯',
  eastmoney_ann: '东财公告',
  eastmoney_research: '东财研报',
  eastmoney_industry: '东财行业研究',
  xueqiu: '雪球',
  sina: '新浪财经',
  sina_guba: '新浪股吧',
  tieba: '百度贴吧',
  cls: '财联社',
  gelonghui: '格隆汇',
  wallstreetcn: '华尔街见闻',
  yicai: '第一财经',
  kr36: '36kr',
  weibo: '微博',
  zhihu: '知乎',
  weixin: '微信',
};

const labelOf = (s: string): string => SOURCE_LABEL[s] || s;

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

interface Props {
  account: SentimentAccount;
  usingMock?: boolean;
}

export function BriefsTab({ account, usingMock }: Props) {
  const { t } = useTranslation();

  const briefsQuery = useBriefs(usingMock ? null : account.id, usingMock ? null : account.ticker);
  const briefs: BriefSummary[] = useMemo(
    () => usingMock ? mockBriefs : (briefsQuery.data?.items ?? []),
    [usingMock, briefsQuery.data],
  );

  // PDF 增强:抓取最新 200 篇 post 用于聚合数据来源/情感/风险
  const postsQuery = usePosts(usingMock ? null : account.id, usingMock ? null : account.ticker, 200);
  const posts: SentimentPost[] = useMemo(
    () => (usingMock ? [] : (postsQuery.data?.items ?? [])),
    [usingMock, postsQuery.data],
  );
  const summary = useMemo(() => computeSummary(posts), [posts]);

  const [explicitId, setExplicitId] = useState<number | null>(null);
  // 默认选中第一个,通过派生值实现(避免 useEffect setState)
  const selectedId = explicitId ?? briefs[0]?.id ?? null;

  // 真实模式拉详情;mock 模式直接从静态拿
  const detailQuery = useBriefDetail(
    usingMock ? null : account.id,
    usingMock ? null : selectedId,
  );

  const selected: Brief | null = usingMock
    ? (mockBriefs.find(b => b.id === selectedId) as Brief | undefined) ?? null
    : (detailQuery.data ?? null);

  const anchors = useMemo(
    () => (selected ? extractAnchors(selected.body) : []),
    [selected],
  );

  const briefRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);

  // 构造 PDF 增强 DOM:封面统计 + 数据源分布 + 风险高亮 + 简报正文 + 页脚
  // 通过临时挂到 document.body 上(off-screen 定位),html2canvas 截图后移除。
  // 这样不影响 React 主渲染流,也保留了所有样式继承。
  const buildPdfDom = (): HTMLDivElement | null => {
    if (!selected) return null;
    const root = document.createElement('div');
    root.style.cssText = 'position:fixed;left:-99999px;top:0;width:780px;background:#ffffff;color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;padding:32px 40px;font-size:13px;line-height:1.6;';

    const top3 = summary.sourceBreakdown.slice(0, 3).map(s => `${labelOf(s.source)}(${s.count})`).join(' · ') || '—';
    const totalSentiment = summary.sentimentBreakdown.bullish + summary.sentimentBreakdown.bearish + summary.sentimentBreakdown.neutral + summary.sentimentBreakdown.mixed;
    const sentRow = (label: string, n: number, color: string): string => {
      const pct = totalSentiment ? Math.round(n * 100 / totalSentiment) : 0;
      return `<div style="flex:1;background:${color}22;border-left:3px solid ${color};padding:8px 10px;border-radius:4px;"><div style="font-size:11px;color:#64748b;">${label}</div><div style="font-size:18px;font-weight:700;color:${color};">${n} <span style="font-size:11px;color:#64748b;font-weight:400;">${pct}%</span></div></div>`;
    };

    const sourceRows = summary.sourceBreakdown.map((s, i) => {
      const max = summary.sourceBreakdown[0]?.count || 1;
      const w = Math.round((s.count / max) * 100);
      const color = i === 0 ? '#0ea5e9' : i < 3 ? '#22c55e' : '#94a3b8';
      return `<tr><td style="padding:4px 8px 4px 0;width:140px;color:#334155;">${labelOf(s.source)}</td><td style="padding:4px 0;width:60px;text-align:right;font-weight:600;color:#0f172a;">${s.count}</td><td style="padding:4px 0 4px 12px;"><div style="background:${color};height:8px;border-radius:2px;width:${w}%;"></div></td></tr>`;
    }).join('');

    const riskItems = summary.highRisk.length === 0
      ? '<div style="padding:10px;background:#f1f5f9;border-radius:4px;color:#64748b;font-size:12px;">本期无高风险信号</div>'
      : summary.highRisk.map(p => {
          const reasons = (p.risk_signals || []).map(r => r.reason || r.type).filter(Boolean).slice(0, 2).join('·');
          return `<div style="padding:8px 10px;border-left:3px solid #dc2626;background:#fef2f2;margin-bottom:6px;border-radius:0 4px 4px 0;"><div style="font-size:12px;color:#991b1b;font-weight:600;margin-bottom:2px;">[${labelOf(p.source)}] ${(p.title || '').slice(0, 80)}</div>${reasons ? `<div style="font-size:11px;color:#7f1d1d;">${reasons}</div>` : ''}</div>`;
        }).join('');

    const tr = summary.timeRange;
    const trText = (tr.earliest && tr.latest)
      ? `${tr.earliest.slice(0, 10)} ~ ${tr.latest.slice(0, 10)}`
      : selected.date;

    root.innerHTML = `
      <!-- 封面 -->
      <div style="border-bottom:3px solid #0ea5e9;padding-bottom:18px;margin-bottom:18px;">
        <div style="font-size:11px;letter-spacing:0.22em;color:#0ea5e9;text-transform:uppercase;font-weight:700;margin-bottom:6px;">SENTIMENT BRIEF</div>
        <div style="font-size:24px;font-weight:800;line-height:1.3;margin-bottom:6px;">${selected.symbol} · ${selected.date}</div>
        <div style="font-size:12px;color:#64748b;">数据范围 ${trText} · 共 ${summary.totalPosts} 条样本 · 主源 ${top3} · 模型 ${selected.model || 'glm-4.5-flash'}</div>
      </div>

      <!-- 情感分布 -->
      <div style="font-size:14px;font-weight:700;margin:14px 0 8px 0;border-left:4px solid #0ea5e9;padding-left:8px;">情感分布</div>
      <div style="display:flex;gap:8px;margin-bottom:18px;">
        ${sentRow('看多', summary.sentimentBreakdown.bullish, '#22c55e')}
        ${sentRow('中性', summary.sentimentBreakdown.neutral, '#94a3b8')}
        ${sentRow('看空', summary.sentimentBreakdown.bearish, '#ef4444')}
        ${sentRow('混合', summary.sentimentBreakdown.mixed, '#f59e0b')}
      </div>

      <!-- 数据来源 -->
      <div style="font-size:14px;font-weight:700;margin:14px 0 8px 0;border-left:4px solid #0ea5e9;padding-left:8px;">数据来源分布(共 ${summary.sourceBreakdown.length} 个源)</div>
      <table style="width:100%;border-collapse:collapse;margin-bottom:18px;font-size:12px;">${sourceRows || '<tr><td style="color:#94a3b8;padding:8px;">无 posts 数据</td></tr>'}</table>

      <!-- 风险高亮 -->
      <div style="font-size:14px;font-weight:700;margin:14px 0 8px 0;border-left:4px solid #dc2626;padding-left:8px;">高风险信号 (Top ${summary.highRisk.length})</div>
      ${riskItems}

      <!-- 简报正文 -->
      <div style="font-size:14px;font-weight:700;margin:24px 0 12px 0;border-left:4px solid #0ea5e9;padding-left:8px;">每日简报</div>
      <div id="__pdf_brief_body" style="font-size:13px;line-height:1.7;"></div>

      <!-- 页脚 -->
      <div style="margin-top:30px;padding-top:14px;border-top:1px solid #e2e8f0;font-size:10px;color:#94a3b8;display:flex;justify-content:space-between;">
        <span>Sentinel · ${new Date().toISOString().slice(0,19).replace('T',' ')}</span>
        <span>${selected.symbol} · ${selected.date}</span>
      </div>
    `;

    // 把 BriefRenderer 已经渲染好的 DOM 克隆到 body 槽里,继承现有 markdown 样式
    const briefSlot = root.querySelector<HTMLDivElement>('#__pdf_brief_body');
    if (briefSlot && briefRef.current) {
      briefSlot.innerHTML = briefRef.current.innerHTML;
    }
    return root;
  };

  const handleExportPdf = async () => {
    if (!selected || !briefRef.current) return;
    setExporting(true);
    let dom: HTMLDivElement | null = null;
    try {
      dom = buildPdfDom() ?? briefRef.current;
      if (dom !== briefRef.current) document.body.appendChild(dom);

      const canvas = await html2canvas(dom, {
        scale: 2,
        useCORS: true,
        backgroundColor: '#ffffff',
      });
      const imgData = canvas.toDataURL('image/png');
      const pdf = new jsPDF('p', 'mm', 'a4');
      const pageW = pdf.internal.pageSize.getWidth();
      const pageH = pdf.internal.pageSize.getHeight();
      const margin = 10;
      const contentW = pageW - margin * 2;
      const imgH = (canvas.height / canvas.width) * contentW;

      // 如果内容高度超出一页,分页
      let yOffset = 0;
      const availH = pageH - margin * 2;
      while (yOffset < imgH) {
        if (yOffset > 0) pdf.addPage();
        pdf.addImage(imgData, 'PNG', margin, margin - yOffset, contentW, imgH);
        yOffset += availH;
      }

      pdf.save(`brief_${selected.symbol}_${selected.date}.pdf`);
    } finally {
      // 清理临时 DOM
      if (dom && dom !== briefRef.current && dom.parentNode) {
        dom.parentNode.removeChild(dom);
      }
      setExporting(false);
    }
  };

  const handleEmail = () => alert('邮件发送(演示)');

  if (!usingMock && briefsQuery.isLoading) {
    return <div className="rounded-xl py-12 text-center text-secondary text-sm" style={cardStyle}>
      {t('common.loading') || 'Loading...'}
    </div>;
  }
  if (!usingMock && briefsQuery.error) {
    return <div className="rounded-xl py-6 px-4 text-sm" style={{ background: 'rgba(239,68,68,0.1)', color: '#dc2626' }}>
      ⚠ {briefsQuery.error instanceof Error ? briefsQuery.error.message : 'Failed to load briefs'}
    </div>;
  }

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[280px_minmax(0,1fr)] gap-4">
      <aside className="rounded-xl p-3 self-start" style={cardStyle}>
        <header className="flex items-center justify-between px-1 mb-2">
          <h4 className="text-sm font-semibold text-primary">
            {t('dashboard.sentiment.briefs.list')}
          </h4>
          <button type="button" onClick={() => alert('临时简报生成(演示)')}
            className="text-xs" style={{ color: 'var(--accent-primary)' }}>
            {t('dashboard.sentiment.briefs.newAdHoc')}
          </button>
        </header>
        {briefs.length === 0 ? (
          <p className="text-xs text-muted px-2 py-4 text-center">尚无简报。</p>
        ) : (
          <ul className="space-y-1">
            {briefs.map(b => (
              <li key={b.id}>
                <button type="button" onClick={() => setExplicitId(b.id)}
                  className="w-full text-left px-2.5 py-2 rounded text-sm transition-colors"
                  style={{
                    background: selectedId === b.id ? 'var(--bg-tertiary)' : 'transparent',
                    color: selectedId === b.id ? 'var(--accent-primary)' : 'var(--text-primary)',
                    border: '1px solid transparent',
                  }}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium">📄 {b.date}</span>
                  </div>
                  <div className="text-[11px] text-muted mt-0.5">
                    {new Date(b.generated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      <section className="grid grid-cols-1 lg:grid-cols-[1fr_180px] gap-4">
        <article className="rounded-xl p-6" style={cardStyle}>
          {!usingMock && detailQuery.isLoading && selectedId ? (
            <p className="text-sm text-muted py-12 text-center">{t('common.loading') || 'Loading...'}</p>
          ) : selected ? (
            <>
              <div ref={briefRef}>
                <BriefRenderer body={selected.body} />
              </div>
              <div className="flex items-center gap-2 mt-6 pt-4" style={{ borderTop: '1px solid var(--border-color)' }}>
                <button type="button" onClick={handleExportPdf} disabled={exporting}
                  className="rounded-md px-3 py-1.5 text-sm font-semibold"
                  style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)', opacity: exporting ? 0.6 : 1 }}>
                  {exporting ? '导出中…' : t('dashboard.sentiment.briefs.exportPdf')}
                </button>
                <button type="button" onClick={handleEmail}
                  className="btn-solid rounded-md px-3 py-1.5 text-sm font-semibold">
                  {t('dashboard.sentiment.briefs.email')}
                </button>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted py-12 text-center">
              {t('dashboard.sentiment.briefs.selectBrief')}
            </p>
          )}
        </article>

        {anchors.length > 0 && (
          <nav className="hidden lg:block sticky self-start" style={{ top: 80 }}>
            <div className="rounded-xl p-4" style={cardStyle}>
              <p className="text-xs font-semibold text-secondary uppercase tracking-wider mb-2">
                {t('dashboard.sentiment.briefs.anchorTitle')}
              </p>
              <ul className="space-y-1.5">
                {anchors.map(a => (
                  <li key={a.id}>
                    <a href={`#${a.id}`} className="text-xs hover:underline block"
                       style={{ color: 'var(--text-secondary)' }}>
                      {a.text}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </nav>
        )}
      </section>
    </div>
  );
}
