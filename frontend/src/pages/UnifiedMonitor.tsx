import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { PageHead } from '../components/PageHead';
import { useAuth } from '../contexts/AuthContext';
import { useAuthModal } from '../contexts/AuthModalContext';

type Provider = {
  id: string;
  name: string;
  transport: 'api' | 'browser';
  status: 'ready' | 'fallback' | 'needs_key' | 'needs_login' | 'disabled';
  configured: boolean;
  reason: string;
};

type Citation = { url: string; title?: string; domain?: string };
type Result = {
  engine: string;
  provider_name: string;
  query: string;
  answer: string;
  citations: Citation[];
  cited_articles?: { article_url: string; citation: Citation }[];
  error?: string | null;
  transport: string;
  target_mentioned?: boolean;
  target_rank?: number | null;
  mentioned_names?: string[];
  raw_answer?: string;
  source_url?: string | null;
  citation_collection?: { complete?: boolean; reason?: string };
  article_citation_status?: string;
  not_attempted?: boolean;
};

type RankItem = { name: string; count: number };
type Job = {
  id: string;
  status: string;
  progress: number;
  brand: string;
  queries: string[];
  engines: string[];
  article_urls?: string[];
  created_at?: string;
  finished_at?: string;
  report_url?: string;
  summary?: {
    successful?: number;
    total?: number;
    mention_rate?: number;
    article_citation_rate?: number | null;
    average_target_rank?: number | null;
    brand_ranking?: { name: string; mentions: number; rank: number }[];
    top_cited_articles?: RankItem[];
    top_citation_domains?: RankItem[];
    engine_mentions?: RankItem[];
    engine_results?: RankItem[];
    mention_breakdown?: RankItem[];
  };
  results: Result[];
};

type SavedProfile = { brand: string; aliases: string; competitors: string; articles: string; keywords: string; queries: string };
type ApiTest = { ok: boolean; message: string; answer_preview?: string };
type BrowserStatus = { available: boolean; sessions: { engine: string; has_session: boolean }[] };

const PROFILE_KEY = 'geo-monitor-profile-v1';

const statusText: Record<Provider['status'], string> = {
  ready: '已配置，待测试',
  fallback: '浏览器服务已配置',
  needs_key: '待配置 API',
  needs_login: '浏览器服务未配置',
  disabled: '已停用',
};

const statusColor: Record<Provider['status'], string> = {
  ready: '#047857',
  fallback: '#1d4ed8',
  needs_key: '#b45309',
  needs_login: '#b91c1c',
  disabled: '#6b7280',
};

async function readJson<T>(url: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('token');
  const headers = new Headers(options?.headers);
  headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : typeof body.message === 'string' ? body.message : `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function splitList(value: string) {
  return value.split(/\r?\n|,/).map(item => item.trim()).filter(Boolean);
}

function loadProfile(): SavedProfile {
  try {
    const saved = JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}') as Partial<SavedProfile>;
    return {
      brand: saved.brand || '', aliases: saved.aliases || '', competitors: saved.competitors || '',
      articles: saved.articles || '', keywords: saved.keywords || '', queries: saved.queries || '',
    };
  } catch {
    return { brand: '', aliases: '', competitors: '', articles: '', keywords: '', queries: '' };
  }
}

function downloadReport(job: Job) {
  const report = {
    report_type: 'geo-monitor-unified',
    generated_at: new Date().toISOString(),
    job: { id: job.id, brand: job.brand, queries: job.queries, engines: job.engines, article_urls: job.article_urls || [], status: job.status },
    summary: job.summary || {},
    evidence: job.results,
  };
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'geo-report-' + job.id + '.json';
  anchor.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(value: string) {
  return value.replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character] || character));
}

function downloadHtmlReport(job: Job) {
  const questionNumbers = new Map<string, number>();
  let nextQuestionNumber = 1;
  const reportRows = job.results.map((result) => {
    if (!questionNumbers.has(result.query)) questionNumbers.set(result.query, nextQuestionNumber++);
    const questionNumber = questionNumbers.get(result.query) || nextQuestionNumber;
    const names = Array.from(new Set((result.mentioned_names || []).filter(Boolean)));
    const brandNames = names.map(name => ({ name, is_target: name.trim().toLowerCase() === job.brand.trim().toLowerCase() }));
    if (result.target_mentioned && !brandNames.some(item => item.is_target)) {
      brandNames.unshift({ name: job.brand, is_target: true });
    }
    const citations = (result.citations || []).map(citation => {
      let domain = citation.domain || '';
      try { domain = domain || new URL(citation.url).hostname.replace(/^www\./, ''); } catch { /* keep the source URL */ }
      return { ...citation, domain };
    });
    const matchedArticleUrls = Array.from(new Set((result.cited_articles || []).map(item => item.article_url).filter(Boolean)));
    const hasAnswer = !result.error && Boolean(result.answer);
    const citationComplete = result.citation_collection?.complete === true || result.article_citation_status === 'not_cited';
    const citationAssessable = hasAnswer && (matchedArticleUrls.length > 0 || citationComplete);
    return {
      question: result.query,
      question_no: questionNumber,
      engine: result.engine,
      engine_name: result.provider_name,
      answer: result.answer || '',
      raw_answer: result.raw_answer || result.answer || '',
      error: result.error || '',
      not_attempted: result.not_attempted === true,
      known_answer: hasAnswer,
      brand_mentioned: hasAnswer ? result.target_mentioned === true : null,
      brand_rank: result.target_rank || null,
      brand_sentiment: null,
      citation_status: job.article_urls?.length ? (matchedArticleUrls.length ? '已引用' : citationAssessable ? '未引用' : '待核查') : '无目标文章',
      citation_assessable: citationAssessable,
      collection_status: result.error ? '不完整' : hasAnswer ? (citationComplete ? '完整' : '不完整') : '未报告',
      source_count: citations.length,
      matched_article_urls: matchedArticleUrls,
      brands: brandNames,
      citations,
      source_url: result.source_url || '',
      reason: result.error || ((result.target_mentioned ? '回答正文中识别到目标品牌。' : '回答正文中未识别到目标品牌。') + (citationComplete ? '' : ' 来源未采全，未发现目标文章不能等同于未引用。') + (result.citation_collection?.reason || '')),
      transport: result.transport || '',
    };
  });
  const successfulRows = reportRows.filter(row => row.known_answer);
  const mentionedRows = successfulRows.filter(row => row.brand_mentioned === true);
  const rankValues = mentionedRows.map(row => row.brand_rank).filter((rank): rank is number => typeof rank === 'number' && rank > 0);
  const citationRows = successfulRows.filter(row => row.matched_article_urls.length > 0);
  const assessedCitationRows = successfulRows.filter(row => row.citation_assessable);
  const averageRank = rankValues.length ? Number((rankValues.reduce((total, value) => total + value, 0) / rankValues.length).toFixed(1)) : null;
  const sourceCounts = new Map<string, number>();
  const brandCounts = new Map<string, number>();
  const brandQuestionCounts = new Map<string, Set<string>>();
  const brandPlatforms = new Map<string, Map<string, number>>();
  const articleCounts = new Map<string, number>();
  const platformStats = new Map<string, { total: number; success: number; mentions: number; cited: number; citationAssessable: number }>();
  for (const row of reportRows) {
    const platform = row.engine_name || row.engine || '未知平台';
    const platformItem = platformStats.get(platform) || { total: 0, success: 0, mentions: 0, cited: 0, citationAssessable: 0 };
    platformItem.total += 1;
    if (row.known_answer) platformItem.success += 1;
    if (row.brand_mentioned === true) platformItem.mentions += 1;
    if (row.matched_article_urls.length) platformItem.cited += 1;
    if (row.citation_assessable) platformItem.citationAssessable += 1;
    platformStats.set(platform, platformItem);
    for (const citation of row.citations) {
      const domain = citation.domain || citation.url;
      if (domain) sourceCounts.set(domain, (sourceCounts.get(domain) || 0) + 1);
    }
    for (const brandItem of row.brands) {
      brandCounts.set(brandItem.name, (brandCounts.get(brandItem.name) || 0) + 1);
      if (!brandQuestionCounts.has(brandItem.name)) brandQuestionCounts.set(brandItem.name, new Set());
      brandQuestionCounts.get(brandItem.name)?.add(row.question);
      if (!brandPlatforms.has(brandItem.name)) brandPlatforms.set(brandItem.name, new Map());
      const platforms = brandPlatforms.get(brandItem.name)!;
      platforms.set(platform, (platforms.get(platform) || 0) + 1);
    }
    for (const article of row.matched_article_urls) articleCounts.set(article, (articleCounts.get(article) || 0) + 1);
  }
  if (!brandCounts.has(job.brand)) brandCounts.set(job.brand, 0);
  const brandRanking = Array.from(brandCounts.entries()).sort((a, b) => b[1] - a[1] || (a[0] === job.brand ? -1 : b[0] === job.brand ? 1 : a[0].localeCompare(b[0], 'zh-CN'))).map(([name, count], index) => ({
    name,
    count,
    question_count: brandQuestionCounts.get(name)?.size || 0,
    platforms: Object.fromEntries(Array.from(brandPlatforms.get(name)?.entries() || [])),
    is_target: name.trim().toLowerCase() === job.brand.trim().toLowerCase(),
    rank: index + 1,
  }));
  const questionMap = new Map<string, { question: string; ranks: number[]; platforms: Set<string>; cited: number }>();
  for (const row of reportRows) {
    const item = questionMap.get(row.question) || { question: row.question, ranks: [], platforms: new Set<string>(), cited: 0 };
    if (row.brand_rank) item.ranks.push(row.brand_rank);
    item.platforms.add(row.engine_name || row.engine);
    if (row.matched_article_urls.length) item.cited += 1;
    questionMap.set(row.question, item);
  }
  const questionRanking = Array.from(questionMap.values()).map((item, index) => ({
    question_no: index + 1,
    question: item.question,
    rank_avg: item.ranks.length ? Number((item.ranks.reduce((a, b) => a + b, 0) / item.ranks.length).toFixed(1)) : null,
    best_rank: item.ranks.length ? Math.min(...item.ranks) : null,
    platform_count: item.platforms.size,
    cited_count: item.cited,
  })).sort((a, b) => (a.rank_avg ?? 999) - (b.rank_avg ?? 999));
  const articleRanking = (job.article_urls || []).map((url, index) => ({ title: '目标文章 ' + (index + 1), url, count: articleCounts.get(url) || 0, platform_count: 0 })).sort((a, b) => b.count - a.count);
  const sourceRanking = Array.from(sourceCounts.entries()).sort((a, b) => b[1] - a[1]).map(([domain, count]) => ({ domain, count }));
  const platforms = Array.from(platformStats.entries()).map(([name, item]) => ({
    name,
    total: item.total,
    success: item.success,
    mentions: item.mentions,
    cited: item.cited,
    mention_rate: item.success ? Number((item.mentions / item.success * 100).toFixed(1)) : 0,
    citation_rate: item.citationAssessable ? Number((item.cited / item.citationAssessable * 100).toFixed(1)) : null,
  }));
  const data = {
    brand: job.brand,
    generated_at: new Date().toISOString(),
    completed_questions: new Set(reportRows.map(row => row.question)).size,
    total_questions: new Set(job.queries).size || reportRows.length,
    run_error: '',
    articles: job.article_urls || [],
    rows: reportRows,
    platforms,
    brand_ranking: brandRanking,
    question_ranking: questionRanking,
    article_ranking: articleRanking,
    source_ranking: sourceRanking,
    summary: {
      total_rows: reportRows.length,
      valid_answers: successfulRows.length,
      mention_count: mentionedRows.length,
      mention_total: successfulRows.length,
      citation_count: citationRows.length,
      citation_total: assessedCitationRows.length,
      citation_unknown: successfulRows.length - assessedCitationRows.length,
      complete_count: successfulRows.filter(row => row.collection_status === '完整').length,
      rank_avg: averageRank,
      top3_count: rankValues.filter(rank => rank <= 3).length,
    },
  };
  const safeJson = JSON.stringify(data).replace(/</g, '\\u003c');
  const reportDate = new Date(data.generated_at).toLocaleString();
  const html = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(job.brand)} · GEO 监测报告</title>
<style>
:root{--bg:#f4f6fa;--surface:#fff;--surface-2:#f8fafc;--line:#e3e8f0;--text:#142033;--muted:#6f7d91;--blue:#2563eb;--blue-soft:#eef4ff;--green:#07865a;--green-soft:#e8f7f0;--amber:#b45309;--amber-soft:#fff5e8;--red:#c9352b;--red-soft:#fff0ee;--shadow:0 1px 2px rgba(15,23,42,.04),0 12px 28px -20px rgba(15,23,42,.28);--radius:10px;--sidebar:230px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}button,input,select{font:inherit}button{cursor:pointer}.shell{display:grid;grid-template-columns:var(--sidebar) minmax(0,1fr);min-height:100vh}.side{position:sticky;top:0;height:100vh;background:var(--surface);border-right:1px solid var(--line);padding:18px 14px;display:flex;flex-direction:column}.brand{display:flex;gap:10px;align-items:center;padding:4px 8px 18px;border-bottom:1px solid var(--line)}.logo{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#2563eb,#12a8c4);color:#fff;display:grid;place-items:center;font-weight:800}.brand strong{display:block;font-size:14px}.brand span{font-size:10px;color:var(--muted)}.nav{padding:16px 2px;display:grid;gap:3px}.nav a{display:block;padding:8px 10px;border-radius:7px;color:#526177;font-weight:550}.nav a:hover,.nav a.active{background:var(--blue-soft);color:var(--blue);text-decoration:none}.side-note{margin-top:auto;border-top:1px solid var(--line);padding:13px 8px;color:var(--muted);font-size:11px}.main{min-width:0}.top{background:var(--surface);border-bottom:1px solid var(--line);padding:20px 26px 16px;display:flex;justify-content:space-between;gap:18px;align-items:flex-start}h1{margin:0;font-size:22px;letter-spacing:0}.subtitle{color:var(--muted);margin-top:4px}.top-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:flex-end}.btn{border:1px solid var(--line);background:var(--surface);border-radius:7px;padding:7px 10px;color:#425168;text-decoration:none}.btn.primary{background:var(--blue);border-color:var(--blue);color:#fff}.pill{display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;font-size:11px;font-weight:650;background:var(--green-soft);color:var(--green)}.content{max-width:1580px;margin:0 auto;padding:22px 26px 64px}.section{margin:0 0 26px;scroll-margin-top:16px}.section-head{display:flex;justify-content:space-between;align-items:end;gap:12px;margin:0 0 10px}h2{font-size:17px;margin:0}.section-head p{color:var(--muted);margin:3px 0 0}.kpi-grid{display:grid;grid-template-columns:repeat(7,minmax(120px,1fr));gap:10px}.kpi{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:13px 14px;box-shadow:var(--shadow);min-height:102px}.kpi-label{color:var(--muted);font-size:11px}.kpi-value{font-size:23px;font-weight:750;margin-top:8px;font-variant-numeric:tabular-nums}.kpi-foot{font-size:10px;color:var(--muted);margin-top:6px}.grid-2{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(300px,.65fr);gap:14px}.grid-2.equal{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);overflow:hidden}.panel-head{padding:14px 16px 10px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.panel-title{font-weight:700}.panel-note{font-size:11px;color:var(--muted);margin-top:2px}.panel-body{padding:14px 16px}.bar-row{display:grid;grid-template-columns:115px 1fr 100px;align-items:center;gap:10px;margin:11px 0}.bar-label{font-weight:600}.bar-track{height:8px;background:#edf1f6;border-radius:5px;overflow:hidden}.bar-fill{height:100%;background:var(--blue);border-radius:inherit}.bar-fill.green{background:var(--green)}.bar-value{text-align:right;font-variant-numeric:tabular-nums;color:#425168}.stat-line{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);padding:9px 0;gap:12px}.stat-line:last-child{border-bottom:0}.stat-line span:first-child{color:var(--muted)}.stat-line strong{font-variant-numeric:tabular-nums}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;min-width:900px}th,td{padding:10px 11px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:11px;color:#5f6c80;background:var(--surface-2);font-weight:700;white-space:nowrap;position:sticky;top:0;z-index:1}td{font-size:12px}tbody tr:hover{background:#fbfcfe}.qcell{min-width:270px;max-width:390px;font-weight:600}.qno{display:inline-block;color:#9aa6b6;font-size:10px;margin-right:6px}.muted{color:var(--muted)}.num{font-variant-numeric:tabular-nums}.status{display:inline-flex;align-items:center;gap:4px;border-radius:999px;padding:3px 7px;font-size:10px;font-weight:700;white-space:nowrap}.yes{background:var(--green-soft);color:var(--green)}.no{background:#f1f4f7;color:#657388}.wait{background:var(--amber-soft);color:var(--amber)}.bad{background:var(--red-soft);color:var(--red)}.target{color:var(--blue);font-weight:700}.controls{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 10px}.controls input,.controls select{border:1px solid var(--line);border-radius:7px;padding:7px 9px;background:var(--surface);color:var(--text)}.controls input{min-width:260px}.empty{padding:20px;text-align:center;color:var(--muted)}details{border-bottom:1px solid var(--line)}details:last-child{border-bottom:0}summary{cursor:pointer;padding:11px 14px;font-weight:600;list-style-position:inside}.evidence{padding:0 14px 16px}.evidence-grid{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr);gap:18px}.evidence-grid pre{background:#f7f9fc;border:1px solid var(--line);border-radius:7px;padding:12px;white-space:pre-wrap;word-break:break-word;max-height:420px;overflow:auto;font:12px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace}.source-list{margin:6px 0 0;padding-left:20px}.source-list li{margin:5px 0}.source-list small{display:block;color:var(--muted)}.target-row{background:#f4f8ff}.badge-target{display:inline-block;margin-left:6px;border-radius:999px;padding:2px 6px;background:var(--blue-soft);color:var(--blue);font-size:10px}.rank-table td:first-child{width:70px;font-weight:700}.pie-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:14px}.pie-panel{display:flex;align-items:center;gap:22px;padding:18px}.pie{width:142px;height:142px;border-radius:50%;position:relative;flex:none;box-shadow:inset 0 0 0 1px rgba(15,23,42,.05)}.pie:after{content:"";position:absolute;inset:34px;border-radius:50%;background:var(--surface)}.pie-center{position:absolute;inset:0;display:grid;place-items:center;z-index:1;text-align:center;font-weight:750;font-size:18px}.pie-center small{display:block;font-size:10px;color:var(--muted);font-weight:500}.legend{display:grid;gap:8px;min-width:0}.legend-row{display:flex;align-items:center;justify-content:space-between;gap:16px}.legend-key{display:flex;align-items:center;gap:7px;min-width:0}.legend-dot{width:9px;height:9px;border-radius:50%;flex:none}.legend-label{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.legend-value{font-variant-numeric:tabular-nums;font-weight:700;white-space:nowrap}.footer{color:var(--muted);font-size:11px;text-align:center;padding:14px 0}@media(max-width:1050px){:root{--sidebar:190px}.kpi-grid{grid-template-columns:repeat(4,minmax(120px,1fr))}.grid-2,.grid-2.equal{grid-template-columns:1fr}}@media(max-width:720px){.shell{display:block}.side{position:relative;height:auto;border-right:0;border-bottom:1px solid var(--line)}.nav{grid-template-columns:repeat(3,1fr)}.side-note{display:none}.top{padding:16px}.content{padding:16px}.kpi-grid{grid-template-columns:repeat(2,minmax(120px,1fr))}.evidence-grid{grid-template-columns:1fr}.controls input{min-width:0;flex:1}}
</style>
</head>
<body>
<div class="shell">
<aside class="side"><div class="brand"><div class="logo">G</div><div><strong>GEO 监测中心</strong><span>独立报告 · ${escapeHtml(job.brand)}</span></div></div><nav class="nav"><a class="active" href="#overview">总览</a><a href="#platforms">平台表现</a><a href="#ranking">排名与构成</a><a href="#questions">问题明细</a><a href="#brands">品牌排名</a><a href="#sources">引用来源</a><a href="#evidence">回答证据</a></nav><div class="side-note">生成时间<br>${escapeHtml(reportDate)}<br><span>${escapeHtml(job.id)}</span></div></aside>
<main class="main">
<header class="top"><div><h1>${escapeHtml(job.brand)} · GEO 监测报告</h1><div class="subtitle">跨平台问题核查、品牌提及、排名和引用来源汇总。品牌名次按回答正文的首次出现顺序计算；引用率仅基于可判定记录。</div></div><div class="top-actions"><span class="pill">${escapeHtml(job.status || '已完成')}</span><button class="btn" onclick="window.print()">打印 / 导出 PDF</button></div></header>
<div class="content">
<section class="section" id="overview"><div class="section-head"><div><h2>本次总览</h2><p>以回答成功的记录作为提及率和排名统计分母。</p></div></div><div class="kpi-grid"><div class="kpi"><div class="kpi-label">问题数</div><div class="kpi-value" id="kpiTotal"></div><div class="kpi-foot">去重后问题</div></div><div class="kpi"><div class="kpi-label">已完成回答</div><div class="kpi-value" id="kpiComplete"></div><div class="kpi-foot">含有效答案</div></div><div class="kpi"><div class="kpi-label">目标品牌提及率</div><div class="kpi-value" id="kpiMention"></div><div class="kpi-foot">已提及 / 有效回答</div></div><div class="kpi"><div class="kpi-label">平均目标排名</div><div class="kpi-value" id="kpiRank"></div><div class="kpi-foot">仅统计已提及回答</div></div><div class="kpi"><div class="kpi-label">前 3 名次数</div><div class="kpi-value" id="kpiTop3"></div><div class="kpi-foot">目标品牌排名 ≤ 3</div></div><div class="kpi"><div class="kpi-label">目标文章引用率</div><div class="kpi-value" id="kpiCitation"></div><div class="kpi-foot">已引用 / 有效回答</div></div><div class="kpi"><div class="kpi-label">来源总数</div><div class="kpi-value" id="kpiSources"></div><div class="kpi-foot">回答中采集的引用</div></div></div></section>
<section class="section" id="platforms"><div class="section-head"><div><h2>平台提及率与引用率</h2><p>按平台拆开查看回答成功、目标品牌提及和目标文章引用。</p></div></div><div class="grid-2"><div class="panel"><div class="panel-head"><div><div class="panel-title">平台表现</div><div class="panel-note">蓝色为提及率，绿色为目标文章引用率</div></div></div><div class="panel-body" id="platformBars"></div></div><div class="panel"><div class="panel-head"><div><div class="panel-title">本次数据状态</div><div class="panel-note">任务和采集范围</div></div></div><div class="panel-body" id="statusStats"></div></div></div></section>
<section class="section" id="ranking"><div class="section-head"><div><h2>排名与构成</h2><p>同时查看问题排名和目标文章被引用情况。</p></div></div><div class="grid-2 equal"><div class="panel"><div class="panel-head"><div><div class="panel-title">问题排名</div><div class="panel-note">按目标品牌平均排名升序</div></div></div><div class="table-wrap"><table class="rank-table"><thead><tr><th>排名</th><th>问题</th><th>平均排名</th><th>最佳</th><th>平台数</th></tr></thead><tbody id="questionRankingBody"></tbody></table></div></div><div class="panel"><div class="panel-head"><div><div class="panel-title">目标文章引用排名</div><div class="panel-note">配置的文章在回答中被匹配的次数</div></div></div><div class="table-wrap"><table class="rank-table"><thead><tr><th>排名</th><th>文章</th><th>引用次数</th></tr></thead><tbody id="articleRankingBody"></tbody></table></div></div></div><div class="pie-grid"><div class="panel pie-panel"><div class="pie" id="mentionPie"><div class="pie-center" id="mentionPieCenter"></div></div><div class="legend" id="mentionLegend"></div></div><div class="panel pie-panel"><div class="pie" id="citationPie"><div class="pie-center" id="citationPieCenter"></div></div><div class="legend" id="citationLegend"></div></div></div></section>
<section class="section" id="questions"><div class="section-head"><div><h2>问题 × 平台明细</h2><p>目标品牌是否提及已经单独列出，可按问题、平台和状态筛选。</p></div></div><div class="panel"><div class="panel-body"><div class="controls"><input id="qSearch" type="search" placeholder="搜索问题"><select id="engineFilter"><option value="all">全部平台</option></select><select id="stateFilter"><option value="all">全部状态</option><option value="mention">目标品牌已提及</option><option value="not_mention">目标品牌未提及</option><option value="cited">目标文章已引用</option><option value="wait">待核查 / 无文章</option><option value="error">回答失败</option><option value="not_run">未执行</option></select></div><div class="table-wrap"><table><thead><tr><th>问题</th><th>平台</th><th>目标品牌是否提及</th><th>品牌排名</th><th>提及位置</th><th>目标文章</th><th>来源完整性</th><th>来源数</th><th>状态</th></tr></thead><tbody id="questionBody"></tbody></table></div></div></div></section>
<section class="section" id="brands"><div class="section-head"><div><h2>品牌提及排名</h2><p>回答中识别到的品牌汇总，目标品牌单独标记。</p></div></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>排名</th><th>品牌</th><th>提及回答数</th><th>提及率</th><th>问题覆盖</th><th>主要平台</th></tr></thead><tbody id="brandBody"></tbody></table></div></div></section>
<section class="section" id="sources"><div class="section-head"><div><h2>引用来源排名</h2><p>回答引用来源按域名聚合。</p></div></div><div class="panel"><div class="table-wrap"><table class="rank-table"><thead><tr><th>排名</th><th>来源域名</th><th>引用次数</th><th>占已采集来源</th></tr></thead><tbody id="sourceBody"></tbody></table></div></div></section>
<section class="section" id="evidence"><div class="section-head"><div><h2>回答证据</h2><p>展开每条记录查看模型判定、回答正文、识别品牌和引用来源。</p></div></div><div class="panel"><div id="evidenceList"></div></div></section>
<div class="footer">报告由 GEO 监测中心生成 · ${escapeHtml(job.id)}</div>
</div></main></div>
<script id="report-data" type="application/json">${safeJson}</script>
<script>
const DATA = JSON.parse(document.getElementById('report-data').textContent);
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const status = (label, kind) => '<span class="status ' + kind + '">' + label + '</span>';
const mentionCell = row => row.brand_mentioned === true ? status('✓ 已提及','yes') : row.brand_mentioned === false ? status('× 未提及','no') : status('待核对','wait');
const citationCell = row => row.citation_status === '已引用' ? status('已引用','yes') : row.citation_status === '未引用' ? status('未引用','no') : status(row.citation_status || '待核查','wait');
const stateCell = row => row.not_attempted ? status('未执行','wait') : row.error ? status('回答失败','bad') : row.known_answer ? status('已完成','yes') : status('无回答','wait');
const pct = value => value == null ? '—' : (Number(value).toFixed(1).replace(/\\.0$/, '') + '%');
const rows = DATA.rows || [];
const validRows = rows.filter(row => row.known_answer);
function renderOverview(){
  document.getElementById('kpiTotal').textContent = DATA.total_questions || new Set(rows.map(row => row.question)).size;
  document.getElementById('kpiComplete').textContent = DATA.summary.valid_answers + ' / ' + rows.length;
  document.getElementById('kpiMention').textContent = pct(DATA.summary.mention_total ? DATA.summary.mention_count / DATA.summary.mention_total * 100 : 0);
  document.getElementById('kpiRank').textContent = DATA.summary.rank_avg == null ? '—' : '#' + DATA.summary.rank_avg;
  document.getElementById('kpiTop3').textContent = DATA.summary.top3_count || 0;
  document.getElementById('kpiCitation').textContent = pct(DATA.summary.citation_total ? DATA.summary.citation_count / DATA.summary.citation_total * 100 : null);
  document.getElementById('kpiSources').textContent = rows.reduce((total, row) => total + Number(row.source_count || 0), 0);
}
function renderPlatforms(){
  const max = Math.max(1, ...(DATA.platforms || []).map(item => Math.max(item.mention_rate, item.citation_rate)));
  document.getElementById('platformBars').innerHTML = (DATA.platforms || []).map(item => '<div class="bar-row"><div class="bar-label">' + esc(item.name) + '</div><div><div class="bar-track"><div class="bar-fill" style="width:' + Math.max(2, item.mention_rate / max * 100) + '%"></div></div><div class="bar-track" style="margin-top:5px"><div class="bar-fill green" style="width:' + Math.max(2, item.citation_rate / max * 100) + '%"></div></div></div><div class="bar-value">提及 ' + pct(item.mention_rate) + '<br>引用 ' + pct(item.citation_rate) + '</div></div>').join('') || '<div class="empty">暂无平台数据</div>';
  const total = rows.length, failed = rows.filter(row => row.error && !row.not_attempted).length, skipped = rows.filter(row => row.not_attempted).length;
  document.getElementById('statusStats').innerHTML = '<div class="stat-line"><span>目标品牌</span><strong>' + esc(DATA.brand) + '</strong></div><div class="stat-line"><span>执行平台</span><strong>' + (DATA.platforms || []).length + '</strong></div><div class="stat-line"><span>问题记录</span><strong>' + total + '</strong></div><div class="stat-line"><span>回答失败</span><strong>' + failed + '</strong></div><div class="stat-line"><span>未执行</span><strong>' + skipped + '</strong></div><div class="stat-line"><span>目标文章</span><strong>' + (DATA.articles || []).length + '</strong></div>';
}
function renderRankings(){
  document.getElementById('questionRankingBody').innerHTML = (DATA.question_ranking || []).map((item, index) => '<tr><td>' + (index + 1) + '</td><td>' + esc(item.question) + '</td><td class="num">' + (item.rank_avg == null ? '—' : '#' + item.rank_avg) + '</td><td class="num">' + (item.best_rank == null ? '—' : '#' + item.best_rank) + '</td><td class="num">' + item.platform_count + '</td></tr>').join('') || '<tr><td colspan="5" class="empty">暂无问题排名</td></tr>';
  document.getElementById('articleRankingBody').innerHTML = (DATA.article_ranking || []).map((item, index) => '<tr><td>' + (index + 1) + '</td><td><a href="' + esc(item.url) + '" target="_blank" rel="noopener">' + esc(item.title) + '</a><div class="muted">' + esc(item.url) + '</div></td><td class="num">' + item.count + '</td></tr>').join('') || '<tr><td colspan="3" class="empty">未配置目标文章</td></tr>';
}
function renderComposition(){
  const mentionYes = Number(DATA.summary.mention_count || 0);
  const mentionNo = Math.max(0, Number(DATA.summary.mention_total || 0) - mentionYes);
  const citationYes = Number(DATA.summary.citation_count || 0);
  const citationNo = Math.max(0, Number(DATA.summary.citation_total || 0) - citationYes);
  const setPie = (id, centerId, legendId, title, yesLabel, yes, noLabel, no, yesColor, unknown = 0) => {
    const known = yes + no, total = known + unknown;
    const degree = total ? yes / total * 360 : 0;
    const knownDegree = total ? known / total * 360 : 0;
    const ratio = known ? (yes / known * 100).toFixed(1).replace(/\\.0$/, '') + '%' : '—';
    document.getElementById(id).style.background = 'conic-gradient(' + yesColor + ' 0deg ' + degree + 'deg,#e7edf5 ' + degree + 'deg ' + knownDegree + 'deg,#f59e0b ' + knownDegree + 'deg 360deg)';
    document.getElementById(centerId).innerHTML = '<div>' + ratio + '<small>' + title + '</small></div>';
    document.getElementById(legendId).innerHTML = '<div class="panel-title">' + title + '</div><div class="legend-row"><span class="legend-key"><i class="legend-dot" style="background:' + yesColor + '"></i><span class="legend-label">' + yesLabel + '</span></span><span class="legend-value">' + yes + '</span></div><div class="legend-row"><span class="legend-key"><i class="legend-dot" style="background:#e7edf5"></i><span class="legend-label">' + noLabel + '</span></span><span class="legend-value">' + no + '</span></div>' + (unknown ? '<div class="legend-row"><span class="legend-key"><i class="legend-dot" style="background:#f59e0b"></i><span class="legend-label">待核查（来源未采全）</span></span><span class="legend-value">' + unknown + '</span></div>' : '') + '<div class="panel-note">回答数：' + total + ' 条；可判定：' + known + ' 条</div>';
  };
  setPie('mentionPie','mentionPieCenter','mentionLegend','目标品牌提及构成','已提及',mentionYes,'未提及',mentionNo,'#2563eb');
  setPie('citationPie','citationPieCenter','citationLegend','目标文章引用构成','已引用',citationYes,'未引用',citationNo,'#07865a',Number(DATA.summary.citation_unknown || 0));
}
function renderQuestions(){
  const query = document.getElementById('qSearch').value.trim().toLowerCase();
  const engine = document.getElementById('engineFilter').value;
  const state = document.getElementById('stateFilter').value;
  const filtered = rows.filter(row => {
    if (query && !String(row.question).toLowerCase().includes(query)) return false;
    if (engine !== 'all' && row.engine !== engine && row.engine_name !== engine) return false;
    if (state === 'mention' && row.brand_mentioned !== true) return false;
    if (state === 'not_mention' && row.brand_mentioned !== false) return false;
    if (state === 'cited' && row.citation_status !== '已引用') return false;
    if (state === 'wait' && row.citation_status !== '待核查' && row.citation_status !== '无目标文章') return false;
    if (state === 'error' && (!row.error || row.not_attempted)) return false;
    if (state === 'not_run' && !row.not_attempted) return false;
    return true;
  });
  document.getElementById('questionBody').innerHTML = filtered.map(row => {
    const position = row.brand_rank ? (row.brand_rank <= 3 ? '前段' : '主体 / 后段') : '—';
    const target = row.brand_mentioned === true ? '<span class="target">✓</span>' : row.brand_mentioned === false ? '<span class="muted">×</span>' : '—';
    return '<tr' + (row.brand_mentioned === true ? ' class="target-row"' : '') + '><td class="qcell"><span class="qno">' + String(row.question_no || '').padStart(2,'0') + '</span>' + esc(row.question) + '</td><td>' + esc(row.engine_name) + '</td><td>' + target + '</td><td class="num">' + (row.brand_rank || '—') + '</td><td>' + position + '</td><td>' + citationCell(row) + '</td><td>' + (row.collection_status === '完整' ? status('完整','yes') : row.collection_status === '不完整' ? status('不完整','wait') : status('未报告','no')) + '</td><td class="num">' + (row.source_count || 0) + '</td><td>' + stateCell(row) + '</td></tr>';
  }).join('') || '<tr><td colspan="9" class="empty">没有符合当前筛选条件的结果</td></tr>';
}
function renderBrands(){
  const denominator = Math.max(1, DATA.summary.valid_answers || validRows.length);
  document.getElementById('brandBody').innerHTML = (DATA.brand_ranking || []).map(item => {
    const platformText = Object.entries(item.platforms || {}).sort((a,b) => b[1] - a[1]).slice(0,3).map(entry => entry[0] + ' (' + entry[1] + ')').join('、') || '—';
    return '<tr' + (item.is_target ? ' class="target-row"' : '') + '><td class="num">' + item.rank + '</td><td><strong>' + esc(item.name) + '</strong>' + (item.is_target ? '<span class="badge-target">目标品牌</span>' : '') + '</td><td class="num">' + item.count + '</td><td class="num">' + pct(item.count / denominator * 100) + '</td><td class="num">' + item.question_count + '</td><td>' + esc(platformText) + '</td></tr>';
  }).join('') || '<tr><td colspan="6" class="empty">暂无品牌提及</td></tr>';
}
function renderSources(){
  const total = Math.max(1, rows.reduce((sum, row) => sum + Number(row.source_count || 0), 0));
  document.getElementById('sourceBody').innerHTML = (DATA.source_ranking || []).map((item,index) => '<tr><td>' + (index + 1) + '</td><td>' + esc(item.domain) + '</td><td class="num">' + item.count + '</td><td class="num">' + pct(item.count / total * 100) + '</td></tr>').join('') || '<tr><td colspan="4" class="empty">暂无引用来源</td></tr>';
}
function renderEvidence(){
  document.getElementById('evidenceList').innerHTML = rows.map(row => {
    const sources = row.citations && row.citations.length ? '<ol class="source-list">' + row.citations.map(source => '<li><a href="' + esc(source.url) + '" target="_blank" rel="noopener">' + esc(source.title || source.url) + '</a><small>' + esc(source.domain || '') + '</small></li>').join('') + '</ol>' : '<div class="empty">没有已采集来源</div>';
    const brands = row.brands && row.brands.length ? row.brands.map(item => esc(item.name) + (item.is_target ? '（目标品牌）' : '')).join('<br>') : '未提取到品牌列表';
    return '<details><summary>' + String(row.question_no || '').padStart(2,'0') + ' · ' + esc(row.question) + ' · ' + esc(row.engine_name) + ' <span class="muted">· 目标品牌 ' + (row.brand_mentioned === true ? '已提及' : row.brand_mentioned === false ? '未提及' : '待核对') + '</span></summary><div class="evidence"><div class="evidence-grid"><div><div class="panel-note">模型判定</div><p>' + mentionCell(row) + ' &nbsp; ' + citationCell(row) + ' &nbsp; ' + stateCell(row) + '</p><p class="muted">' + esc(row.reason || '暂无判定说明') + '</p><div class="panel-note">回答正文</div><pre>' + esc(row.answer || row.error || '暂无回答') + '</pre>' + (row.raw_answer && row.raw_answer !== row.answer ? '<details><summary>原始采集文本（含搜索过程）</summary><pre>' + esc(row.raw_answer) + '</pre></details>' : '') + '</div><div><div class="panel-note">识别到的品牌</div><p>' + brands + '</p><div class="panel-note">引用来源</div>' + sources + '</div></div></div></details>';
  }).join('') || '<div class="empty">暂无回答证据</div>';
}
const engineSelect = document.getElementById('engineFilter');
(DATA.platforms || []).forEach(item => { const option = document.createElement('option'); option.value = item.name; option.textContent = item.name; engineSelect.appendChild(option); });
['qSearch','engineFilter','stateFilter'].forEach(id => document.getElementById(id).addEventListener('input', renderQuestions));
renderOverview(); renderPlatforms(); renderRankings(); renderComposition(); renderQuestions(); renderBrands(); renderSources(); renderEvidence();
</script>
</body>
</html>`;
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'geo-report-' + job.id + '.html';
  anchor.click();
  URL.revokeObjectURL(url);
}

function buildQuestions(keywords: string[], brand: string) {
  const questions = keywords.flatMap(keyword => [
    '在' + keyword + '领域，有哪些品牌值得重点关注？',
    '选择' + keyword + '相关产品或服务时，应该对比哪些品牌？',
    brand + '在' + keyword + '领域与其他品牌相比有哪些优势？',
  ]);
  return [...new Set(questions)];
}

export function UnifiedMonitor() {
  const { token, isAdmin, clearAuth } = useAuth();
  const { openAuthModal } = useAuthModal();
  const [savedProfile] = useState(loadProfile);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [history, setHistory] = useState<Job[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [brand, setBrand] = useState(savedProfile.brand);
  const [aliases, setAliases] = useState(savedProfile.aliases);
  const [competitors, setCompetitors] = useState(savedProfile.competitors);
  const [articles, setArticles] = useState(savedProfile.articles);
  const [keywords, setKeywords] = useState(savedProfile.keywords);
  const [queries, setQueries] = useState(savedProfile.queries);
  const [mode, setMode] = useState<'auto' | 'api' | 'browser'>('auto');
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [testingProvider, setTestingProvider] = useState('');
  const [apiTests, setApiTests] = useState<Record<string, ApiTest>>({});
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState('');
  const [configProvider, setConfigProvider] = useState('deepseek');
  const [endpoint, setEndpoint] = useState('');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [hasKey, setHasKey] = useState(false);
  const [configMessage, setConfigMessage] = useState('');
  const [browserStatus, setBrowserStatus] = useState<BrowserStatus>({ available: false, sessions: [] });

  const refreshProviders = useCallback(async () => {
    const data = await readJson<{ providers: Provider[] }>('/api/unified/providers');
    setProviders(data.providers);
    setSelected(current => current.length ? current : data.providers.filter(provider => provider.status === 'ready' || provider.status === 'fallback').map(provider => provider.id));
  }, []);

  const refreshHistory = useCallback(async () => {
    try {
      const data = await readJson<{ jobs: Job[] }>('/api/unified/jobs?limit=20');
      setHistory(data.jobs || []);
      setHistoryError('');
    } catch (requestError) {
      setHistoryError(requestError instanceof Error ? requestError.message : '读取历史任务失败');
    }
  }, []);

  useEffect(() => {
    if (!token || !isAdmin) return;
    refreshProviders().catch(() => setError('无法读取服务状态，请先启动后端服务。'));
    void refreshHistory();
    readJson<BrowserStatus>('/api/unified/browser-sessions').then(setBrowserStatus).catch(() => undefined);
  }, [refreshProviders, refreshHistory, token, isAdmin]);

  useEffect(() => {
    if (!token || !isAdmin) return;
    let active = true;
    setApiKey('');
    setEndpoint('');
    setModel('');
    setHasKey(false);
    setConfigMessage('');
    readJson<{ endpoint: string; model: string; has_key: boolean }>('/api/unified/providers/' + configProvider + '/config')
      .then(config => { if (active) { setEndpoint(config.endpoint); setModel(config.model); setHasKey(config.has_key); } })
      .catch(err => { if (active) setConfigMessage(err instanceof Error ? err.message : '读取配置失败'); });
    return () => { active = false; };
  }, [configProvider, token, isAdmin]);

  const saveConfig = async () => {
    try {
      await readJson('/api/unified/providers/' + configProvider + '/config', { method: 'PUT', body: JSON.stringify({ endpoint, model, api_key: apiKey }) });
      setApiKey(''); setHasKey(true); setConfigMessage('配置已保存，请测试连接。');
      await refreshProviders();
    } catch (err) { setConfigMessage(err instanceof Error ? err.message : '保存失败'); }
  };

  const clearConfig = async () => {
    try {
      await readJson('/api/unified/providers/' + configProvider + '/config', { method: 'DELETE' });
      setEndpoint(''); setModel(''); setApiKey(''); setHasKey(false); setConfigMessage('配置已删除。');
      await refreshProviders();
    } catch (err) { setConfigMessage(err instanceof Error ? err.message : '删除失败'); }
  };

  const downloadServerReport = async (url: string) => {
    try {
      const response = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw new Error('报告下载失败');
      const blobUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = blobUrl;
      link.download = `geo-report-${job?.id || 'report'}.json`;
      link.click();
      URL.revokeObjectURL(blobUrl);
    } catch (err) { setError(err instanceof Error ? err.message : '报告下载失败'); }
  };

  useEffect(() => {
    localStorage.setItem(PROFILE_KEY, JSON.stringify({ brand, aliases, competitors, articles, keywords, queries }));
  }, [brand, aliases, competitors, articles, keywords, queries]);

  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return;
    const timer = window.setInterval(() => {
      readJson<Job>('/api/unified/jobs/' + job.id).then(updated => {
        setJob(updated);
        if (!['queued', 'running'].includes(updated.status)) {
          window.clearInterval(timer);
          void refreshHistory();
        }
      }).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, refreshHistory]);

  const readyCount = providers.filter(provider => provider.transport === 'api' && provider.configured).length;
  const workerCount = browserStatus.sessions.filter(session => session.has_session).length;
  const summary = job?.summary;
  const maxBrandMentions = Math.max(1, ...(summary?.brand_ranking || []).map(item => item.mentions));
  const displayedProviders = useMemo(() => providers.filter(provider => provider.status !== 'disabled'), [providers]);

  const launch = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    const queryList = splitList(queries);
    if (!brand.trim() || queryList.length === 0) {
      setError('请填写目标品牌和至少一个监测问题。');
      return;
    }
    if (selected.length === 0) {
      setError('请至少选择一个监测平台。');
      return;
    }
    setLoading(true);
    try {
      const created = await readJson<{ job_id: string }>('/api/unified/jobs', {
        method: 'POST',
        body: JSON.stringify({
          brand: brand.trim(),
          aliases: splitList(aliases),
          competitor_brands: splitList(competitors),
          article_urls: splitList(articles),
          queries: queryList,
          engines: selected,
          mode,
        }),
      });
      const nextJob = await readJson<Job>('/api/unified/jobs/' + created.job_id);
      setJob(nextJob);
      await refreshHistory();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '任务创建失败');
    } finally {
      setLoading(false);
    }
  };

  const testProvider = async (provider: Provider) => {
    setTestingProvider(provider.id);
    setApiTests(current => ({ ...current, [provider.id]: { ok: false, message: '正在发送测试请求…' } }));
    try {
      const result = await readJson<ApiTest>('/api/unified/providers/' + provider.id + '/test', { method: 'POST' });
      setApiTests(current => ({ ...current, [provider.id]: result }));
    } catch (requestError) {
      setApiTests(current => ({ ...current, [provider.id]: { ok: false, message: requestError instanceof Error ? requestError.message : '测试失败' } }));
    } finally {
      setTestingProvider('');
    }
  };

  const toggleProvider = (id: string) => {
    setSelected(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id]);
  };

  const generateQuestions = () => {
    const terms = splitList(keywords);
    if (terms.length === 0) {
      setError('先填写一个行业主题或关键词。');
      return;
    }
    const generated = buildQuestions(terms, brand.trim() || '目标品牌');
    setQueries(current => [...new Set([...splitList(current), ...generated])].join('\n'));
    setError('');
  };

  const openHistory = (saved: Job) => {
    setJob(saved);
    window.requestAnimationFrame(() => document.getElementById('report')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  return (
    <div className="-mt-16 min-h-screen" style={{ background: 'var(--bg-primary)', color: 'var(--text-primary)' }}>
      <PageHead titleKey="unified.title" descriptionKey="unified.description" titleFallback="GEO 监测中心" descriptionFallback="管理品牌、监测问题和 AI 平台检测记录" />
      <header className="border-b sticky top-0 z-20 backdrop-blur" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-nav)' }}>
        <div className="max-w-7xl mx-auto px-5 sm:px-6 py-3.5 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-md grid place-items-center shrink-0 text-white font-semibold" style={{ background: '#0f766e' }}>G</div>
            <div className="min-w-0"><div className="text-xs text-muted">GEO MONITOR</div><h1 className="text-lg font-semibold leading-6">品牌监测工作台</h1></div>
          </div>
          <div className="flex gap-4 items-center"><a href="#history" className="text-sm text-muted hover:text-primary whitespace-nowrap">历史任务</a>{token ? <button type="button" onClick={clearAuth} className="text-sm">退出登录</button> : <button type="button" onClick={() => openAuthModal('login')} className="text-sm">管理员登录</button>}</div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-5 sm:px-6 py-6 space-y-6">
        {!isAdmin && <div className="border rounded-md p-4 text-sm" style={{ borderColor: 'var(--border-color)' }}>{token ? '当前账号没有管理员权限。' : '请先登录管理员账号，配置平台并开始监测。'} <button type="button" className="text-blue-700 ml-2" onClick={() => openAuthModal('login')}>管理员登录</button></div>}
        <section className="grid gap-3 sm:grid-cols-2">
          <Metric label="已配置模型服务" value={String(readyCount)} hint="需点击测试连接验证真实可用性" />
          <Metric label="已保存浏览器会话" value={String(workerCount)} hint={browserStatus.available ? '已保存不代表登录仍有效' : '浏览器服务未连接'} />
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_350px] items-start">
          <form onSubmit={launch} className="border rounded-lg px-5 sm:px-6" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="py-4 border-b" style={{ borderColor: 'var(--border-color)' }}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><h2 className="text-base font-semibold">品牌与监测配置</h2><p className="text-sm text-muted mt-1">品牌资料会保存在当前浏览器中。</p></div>
                <label className="text-xs text-muted flex items-center gap-2">采集方式
                  <select value={mode} onChange={event => setMode(event.target.value as typeof mode)} className="px-2.5 py-2 rounded-md border text-sm text-primary" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-color)' }}>
                    <option value="auto">自动优先 API</option><option value="api">仅 API</option><option value="browser">仅浏览器 Worker</option>
                  </select>
                </label>
              </div>
            </div>

            <section className="py-5 border-b" style={{ borderColor: 'var(--border-color)' }}>
              <h3 className="text-sm font-semibold mb-3">1. 品牌资料</h3>
              <div className="grid gap-3 md:grid-cols-2">
                <Field label="目标品牌" value={brand} onChange={setBrand} placeholder="填写需要监测的品牌" />
                <Field label="品牌别名" value={aliases} onChange={setAliases} placeholder="每行一个，也可用逗号分隔" />
                <TextField label="竞品品牌" value={competitors} onChange={setCompetitors} rows={3} placeholder="每行一个，用于回答中的品牌排名" />
                <TextField label="已发布文章链接" value={articles} onChange={setArticles} rows={3} placeholder={'每行一个完整链接\nhttps://example.com/article'} />
              </div>
              <p className="text-xs text-muted mt-2">目标文章引用按回答返回的来源链接进行匹配；未返回引用的回答不会判定为已引用。</p>
            </section>

            <section className="py-5 border-b" style={{ borderColor: 'var(--border-color)' }}>
              <div className="flex flex-wrap items-end justify-between gap-3 mb-3">
                <div><h3 className="text-sm font-semibold">2. 监测主题与问题</h3><p className="text-xs text-muted mt-1">问题生成使用本地模板，不消耗模型调用；生成后可直接修改。</p></div>
                <button type="button" onClick={generateQuestions} className="px-3 py-2 rounded-md border text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>根据主题生成问题</button>
              </div>
              <TextField label="行业主题 / 关键词" value={keywords} onChange={setKeywords} rows={2} placeholder={'例如：企业协作软件\n私域运营'} />
              <div className="mt-3"><TextField label="监测问题" value={queries} onChange={setQueries} rows={5} placeholder={'每行一个问题，例如：\n企业协作软件有哪些品牌值得关注？'} /></div>
            </section>

            <section className="py-5">
              <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                <div><h3 className="text-sm font-semibold">3. 选择监测平台</h3><p className="text-xs text-muted mt-1">保存 API 配置后测试连接，再选择监测平台。</p></div>
                <button type="button" className="text-xs text-blue-700" onClick={() => setSelected(displayedProviders.filter(provider => provider.status === 'ready' || provider.status === 'fallback').map(provider => provider.id))}>选择已配置的平台</button>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                {displayedProviders.map(provider => {
                  const active = selected.includes(provider.id);
                  const test = apiTests[provider.id];
                  return <div key={provider.id} className="border rounded-md p-3" style={{ borderColor: active ? '#0f766e' : 'var(--border-color)', background: active ? 'rgba(15,118,110,.05)' : 'var(--bg-surface)' }}>
                    <label className="flex items-center justify-between gap-3 cursor-pointer">
                      <span className="flex items-center gap-2 min-w-0"><input type="checkbox" checked={active} onChange={() => toggleProvider(provider.id)} className="accent-teal-700" /><span className="font-medium text-sm truncate">{provider.name}</span></span>
                      <span className="text-[11px] text-right shrink-0" style={{ color: statusColor[provider.status] }}>{statusText[provider.status]}</span>
                    </label>
                    <div className="mt-2 flex items-center justify-between gap-3"><span className="text-xs text-muted">{provider.transport === 'api' ? '服务端 API' : '浏览器 Worker'}</span>
                      {provider.transport === 'api' && <button type="button" disabled={!provider.configured || testingProvider === provider.id} onClick={() => void testProvider(provider)} className="text-xs px-2.5 py-1 rounded border disabled:opacity-40" style={{ borderColor: 'var(--border-color)' }}>{testingProvider === provider.id ? '测试中…' : '测试连接'}</button>}
                    </div>
                    {test && <div className="mt-2 text-xs" style={{ color: test.ok ? '#047857' : '#b91c1c' }}>{test.message}{test.answer_preview ? ' · ' + test.answer_preview : ''}</div>}
                  </div>;
                })}
              </div>
              {error && <div className="mt-4 px-3 py-2 rounded-md text-sm" style={{ color: '#b91c1c', background: '#fef2f2' }}>{error}</div>}
              <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                <p className="text-xs text-muted">本次约 {queryCount(queries) * selected.length} 次平台查询，服务商可能按调用量计费。</p>
                <button type="submit" disabled={loading || !isAdmin} className="px-5 py-2.5 rounded-md text-sm font-medium text-white disabled:opacity-50" style={{ background: '#0f766e' }}>{loading ? '创建中…' : '开始监测'}</button>
              </div>
            </section>
          </form>

          <aside className="space-y-5">
            <section className="border rounded-lg p-5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <h2 className="text-base font-semibold">平台 API 配置</h2>
              <p className="text-xs text-muted mt-2">填写服务商或授权网关提供的 Chat Completions 完整地址、模型名称和 Key。Key 由服务商提供，不由本系统生成。</p>
              <div className="mt-4 space-y-3">
                <label className="block text-xs font-medium">平台<select value={configProvider} disabled={!isAdmin} onChange={event => setConfigProvider(event.target.value)} className="mt-1 w-full px-3 py-2 border rounded-md text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}><option value="deepseek">DeepSeek</option><option value="doubao">豆包</option><option value="yuanbao">元宝</option><option value="wenxin">文心一言</option><option value="qwen">通义千问</option></select></label>
                <label className="block text-xs font-medium">请求地址<input value={endpoint} disabled={!isAdmin} onChange={event => setEndpoint(event.target.value)} placeholder="https://.../chat/completions" className="mt-1 w-full px-3 py-2 border rounded-md text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }} /></label>
                <label className="block text-xs font-medium">模型名称<input value={model} disabled={!isAdmin} onChange={event => setModel(event.target.value)} placeholder="服务商提供的模型 ID" className="mt-1 w-full px-3 py-2 border rounded-md text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }} /></label>
                <label className="block text-xs font-medium">API Key<input type="password" autoComplete="new-password" value={apiKey} disabled={!isAdmin} onChange={event => setApiKey(event.target.value)} placeholder={hasKey ? '已保存，留空保持不变' : '输入 API Key'} className="mt-1 w-full px-3 py-2 border rounded-md text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }} /></label>
                <div className="flex gap-2"><button type="button" disabled={!isAdmin} onClick={() => void saveConfig()} className="px-3 py-2 rounded-md text-white text-sm disabled:opacity-40" style={{ background: '#0f766e' }}>保存配置</button><button type="button" disabled={!isAdmin || !hasKey} onClick={() => void clearConfig()} className="px-3 py-2 rounded-md border text-sm disabled:opacity-40" style={{ borderColor: 'var(--border-color)' }}>删除配置</button></div>
                {configMessage && <p className="text-xs">{configMessage}</p>}
                <p className="text-xs text-muted">保存只表示配置已记录。连接测试会发送真实请求，可能产生费用；接口和网页回答可能不同，且不一定返回来源。</p>
              </div>
            </section>

            <section className="border rounded-lg p-5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <h2 className="text-base font-semibold">浏览器账号状态</h2>
              <p className="text-xs text-muted mt-2">{browserStatus.available ? '浏览器服务已连接。保存会话不代表登录仍有效。' : '浏览器服务未连接，当前无法检测账号登录状态。'}</p>
              <div className="mt-3 space-y-2">{[['deepseek', 'DeepSeek'], ['doubao', '豆包'], ['yuanbao', '元宝'], ['wenxin', '文心一言'], ['qwen', '通义千问']].map(([id, name]) => <div key={id} className="flex justify-between gap-3 text-xs"><span>{name}</span><span className="text-muted">{!browserStatus.available ? '服务未连接' : browserStatus.sessions.find(item => item.engine === id)?.has_session ? '已保存会话，未验证' : '未保存会话'}</span></div>)}</div>
              <p className="text-xs text-muted mt-3">网页内扫码授权尚未接通会话保存，请使用 API；浏览器模式需要部署并维护浏览器服务。</p>
            </section>

            <section id="history" className="border rounded-lg p-5 scroll-mt-20" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="flex items-center justify-between gap-2"><h2 className="text-base font-semibold">历史任务</h2><button type="button" onClick={() => void refreshHistory()} className="text-xs text-blue-700">刷新</button></div>
              {historyError ? <p className="text-xs mt-3" style={{ color: '#b91c1c' }}>{historyError}</p> : history.length === 0 ? <p className="text-sm text-muted mt-3">暂无监测记录。</p> : <div className="mt-3 divide-y" style={{ borderColor: 'var(--border-color)' }}>
                {history.slice(0, 8).map(saved => <button type="button" key={saved.id} onClick={() => openHistory(saved)} className="w-full text-left py-3 first:pt-0 last:pb-0">
                  <div className="flex items-center justify-between gap-3"><span className="text-sm font-medium truncate">{saved.brand}</span><span className="text-[11px] text-muted shrink-0">{saved.summary?.mention_rate ?? '—'}%</span></div>
                  <div className="mt-1 flex items-center justify-between gap-3 text-xs text-muted"><span>{formatDate(saved.created_at)}</span><span>{saved.queries?.length || 0} 个问题 · {saved.status}</span></div>
                </button>)}
              </div>}
            </section>

            {job && <section className="border rounded-lg p-5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="flex items-center justify-between gap-3"><h2 className="text-base font-semibold">当前任务</h2><div className="flex gap-2"><button type="button" onClick={() => downloadHtmlReport(job)} className="text-xs px-2.5 py-1.5 rounded border" style={{ borderColor: 'var(--border-color)' }}>HTML</button><button type="button" onClick={() => downloadReport(job)} className="text-xs px-2.5 py-1.5 rounded border" style={{ borderColor: 'var(--border-color)' }}>JSON</button></div></div>
              <div className="mt-3 text-sm">{job.brand}</div><div className="mt-1 text-xs text-muted">{job.status} · {job.progress}%</div>
              <div className="mt-3 h-1.5 rounded-full" style={{ background: 'var(--bg-tertiary)' }}><div className="h-full rounded-full" style={{ width: job.progress + '%', background: '#0f766e' }} /></div>
              <div className="grid grid-cols-2 gap-2 mt-4"><Metric compact label="品牌提及率" value={(job.summary?.mention_rate ?? 0) + '%'} hint="成功回答" /><Metric compact label="文章引用率" value={job.summary?.article_citation_rate == null ? '—' : job.summary.article_citation_rate + '%'} hint="仅以来源可核查记录为分母" /></div>
              {job.report_url && <button type="button" className="inline-block mt-3 text-xs text-blue-700" onClick={() => void downloadServerReport(job.report_url!)}>下载服务器报告</button>}
            </section>}
          </aside>
        </section>

        {job && <div id="report" className="space-y-5 scroll-mt-20">
          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="目标品牌提及率" value={(summary?.mention_rate ?? 0) + '%'} hint="成功回答中提及目标品牌的比例" />
            <Metric label="目标文章引用率" value={summary?.article_citation_rate == null ? '—' : summary.article_citation_rate + '%'} hint="仅以来源可核查的成功回答为分母" />
            <Metric label="平均目标排名" value={summary?.average_target_rank ? '#' + summary.average_target_rank : '—'} hint="目标品牌在答案中的出现顺序" />
            <Metric label="有效回答" value={String(summary?.successful ?? 0)} hint={'共 ' + (summary?.total ?? job.results.length) + ' 条平台回答'} />
          </section>

          <section className="grid gap-5 xl:grid-cols-3">
            <Panel title="品牌提及排名">
              {(summary?.brand_ranking || []).length === 0 ? <Empty /> : <div className="space-y-3">{summary?.brand_ranking?.map(item => <div key={item.rank + '-' + item.name}><div className="flex justify-between gap-3 text-sm mb-1"><span className="truncate"><b className="mr-2">#{item.rank}</b>{item.name}</span><span className="text-muted shrink-0">{item.mentions} 次</span></div><div className="h-1.5 rounded-full" style={{ background: 'var(--bg-tertiary)' }}><div className="h-full rounded-full" style={{ width: Math.max(8, item.mentions / maxBrandMentions * 100) + '%', background: item.rank === 1 ? '#0f766e' : '#5eead4' }} /></div></div>)}</div>}
            </Panel>
            <Panel title="目標文章引用排名">
              {(summary?.top_cited_articles || []).length === 0 ? <Empty /> : <RankList data={summary?.top_cited_articles || []} />}
            </Panel>
            <Panel title="引用来源排名">
              {(summary?.top_citation_domains || []).length === 0 ? <Empty /> : <RankList data={summary?.top_citation_domains || []} />}
            </Panel>
          </section>

          <section className="grid gap-5 xl:grid-cols-3">
            <Panel title="平台提及构成"><PieChart data={summary?.engine_mentions || []} empty="当前没有成功的品牌提及数据。" /></Panel>
            <Panel title="目标品牌提及构成"><PieChart data={summary?.mention_breakdown || []} empty="当前没有成功答案。" /></Panel>
            <Panel title="引用来源构成"><PieChart data={summary?.top_citation_domains || []} empty="当前没有引用来源数据。" /></Panel>
          </section>

          <section className="border rounded-lg overflow-hidden" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
            <div className="px-5 py-4 border-b flex items-center justify-between gap-4" style={{ borderColor: 'var(--border-color)' }}><div><h2 className="text-base font-semibold">全部问题核查明细</h2><p className="text-xs text-muted mt-1">回答、品牌排名、目标文章引用与来源都可在此核对。</p></div><span className="text-xs text-muted whitespace-nowrap">{job.results.length} 条结果</span></div>
            <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-muted" style={{ background: 'var(--bg-surface)' }}><th className="px-4 py-3 min-w-64">问题</th><th className="px-4 py-3">平台</th><th className="px-4 py-3">品牌提及</th><th className="px-4 py-3">品牌排名</th><th className="px-4 py-3">目标文章引用</th><th className="px-4 py-3 min-w-72">答案与证据</th><th className="px-4 py-3">状态</th></tr></thead><tbody>{job.results.map((result, index) => <tr key={result.engine + '-' + result.query + '-' + index} className="border-t align-top" style={{ borderColor: 'var(--border-color)' }}>
              <td className="px-4 py-3 min-w-64">{result.query}</td><td className="px-4 py-3 whitespace-nowrap">{result.provider_name}</td>
              <td className="px-4 py-3 text-center font-semibold" style={{ color: result.error ? 'var(--text-muted)' : result.target_mentioned ? '#047857' : '#b91c1c' }}>{result.error ? '—' : result.target_mentioned ? '✓' : '✕'}</td>
              <td className="px-4 py-3 whitespace-nowrap">{result.target_rank ? '#' + result.target_rank : '—'}</td>
              <td className="px-4 py-3 min-w-48">{result.error ? '—' : result.cited_articles?.length ? <div className="space-y-1">{result.cited_articles.map((item, articleIndex) => <a key={item.article_url + articleIndex} href={item.article_url} target="_blank" rel="noreferrer" className="block max-w-56 truncate text-blue-700" title={item.article_url}>{item.article_url}</a>)}</div> : <span className="text-muted">✕</span>}</td>
              <td className="px-4 py-3 min-w-72"><details><summary className="cursor-pointer text-blue-700">查看原始答案（{result.citations?.length || 0} 个来源）</summary><div className="mt-3 space-y-3"><div className="whitespace-pre-wrap text-xs leading-5" style={{ color: 'var(--text-secondary)' }}>{result.answer || '没有返回答案。'}</div>{result.citations?.length ? <div className="space-y-1">{result.citations.map((citation, citationIndex) => <a key={(citation.url || '') + citationIndex} href={citation.url} target="_blank" rel="noreferrer" className="block text-xs text-blue-700 truncate hover:underline">[{citationIndex + 1}] {citation.title || citation.domain || citation.url}</a>)}</div> : null}</div></details></td>
              <td className="px-4 py-3 whitespace-nowrap">{result.error ? <span style={{ color: '#b91c1c' }}>{result.error}</span> : <span style={{ color: '#047857' }}>{result.transport}</span>}</td>
            </tr>)}</tbody></table></div>
          </section>
        </div>}
      </main>
    </div>
  );
}
function queryCount(value: string) {
  return splitList(value).length;
}

function formatDate(value?: string) {
  if (!value) return '时间未知';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString();
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="block text-sm"><span className="block text-muted mb-1.5">{label}</span><input value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} className="w-full px-3 py-2 rounded-md border" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-color)' }} /></label>;
}

function TextField({ label, value, onChange, placeholder, rows }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; rows: number }) {
  return <label className="block text-sm"><span className="block text-muted mb-1.5">{label}</span><textarea value={value} onChange={event => onChange(event.target.value)} rows={rows} placeholder={placeholder} className="w-full px-3 py-2 rounded-md border resize-y" style={{ background: 'var(--bg-surface)', borderColor: 'var(--border-color)' }} /></label>;
}

function Metric({ label, value, hint, compact = false }: { label: string; value: string; hint: string; compact?: boolean }) {
  return <div className={(compact ? 'p-3' : 'p-4') + ' rounded-md border min-w-0'} style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}><div className="text-xs text-muted">{label}</div><div className={(compact ? 'text-lg' : 'text-2xl') + ' font-semibold mt-1 tabular-nums'}>{value}</div><div className="text-xs text-muted mt-1">{hint}</div></div>;
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="border rounded-lg p-5 min-w-0" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}><h2 className="text-sm font-semibold mb-4">{title}</h2>{children}</section>;
}

function RankList({ data }: { data: RankItem[] }) {
  return <div className="space-y-2">{data.map((item, index) => <div key={item.name} className="flex items-start justify-between gap-3 border-b last:border-0 pb-2 last:pb-0" style={{ borderColor: 'var(--border-color)' }}><span className="text-sm min-w-0"><b className="inline-block w-6 text-muted">{index + 1}</b><span className="break-all">{item.name}</span></span><span className="text-sm font-medium shrink-0">{item.count}</span></div>)}</div>;
}

function Empty() {
  return <div className="text-sm text-muted py-4">暂无可统计数据。</div>;
}

type PieItem = { name: string; count: number };

function PieChart({ data, empty }: { data: PieItem[]; empty: string }) {
  const items = data.filter(item => item.count > 0);
  const total = items.reduce((sum, item) => sum + item.count, 0);
  if (!total) return <div className="text-sm text-muted py-4">{empty}</div>;
  const colors = ['#0f766e', '#2563eb', '#f59e0b', '#db2777', '#7c3aed', '#0891b2', '#65a30d', '#ea580c'];
  let cursor = 0;
  const stops = items.map((item, index) => {
    const start = cursor;
    cursor += item.count / total * 100;
    return colors[index % colors.length] + ' ' + start + '% ' + cursor + '%';
  }).join(', ');
  return <div className="flex items-center gap-4"><div className="relative w-24 h-24 rounded-full shrink-0" style={{ background: 'conic-gradient(' + stops + ')' }}><div className="absolute inset-4 rounded-full flex items-center justify-center text-xs font-semibold" style={{ background: 'var(--bg-card)' }}>{total}</div></div><div className="min-w-0 space-y-2 flex-1">{items.slice(0, 8).map((item, index) => <div key={item.name} className="flex items-center justify-between gap-2 text-xs"><span className="flex items-center gap-2 min-w-0"><span className="w-2.5 h-2.5 rounded-sm shrink-0" style={{ background: colors[index % colors.length] }} /><span className="truncate">{item.name}</span></span><span className="tabular-nums text-muted">{item.count}</span></div>)}</div></div>;
}



