// 高级筛选 modal — 贴 WisersOne 原型图 image.png 的结构.
//
// 布局:
//   - 左主区(grow):filter 行,每行 = 标签 + 「全部 N」chip + 多个 checkbox 选项
//                  组与组之间用虚线分隔
//                  组 1:媒体类型 / 媒体分类 / 热门媒体
//                  组 2:全文情感 / 风险等级
//   - 右侧栏(280px):关键字 / 起始时间 / 结束时间 三个输入
//   - 底部:重置 / 取消 / 保存(蓝)三个按钮
//
// 「全部」chip = 该维度清空(没有任何具体选项被勾时它处于"激活"状态).
// modal 内全部用 draft state,确认后才 commit;关闭即卸载,draft 自然丢弃.
import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

import {
  MEDIA_TYPE_ORDER, INDUSTRY_ORDER,
} from '../../../../constants/sentimentPlatforms';
import type {
  SentimentPlatform, RiskLevel, SentimentLabel,
} from '../../../../types/sentiment';

const ALL_RISKS: RiskLevel[] = ['none', 'low', 'medium', 'high'];
const ALL_SENTIMENTS: SentimentLabel[] = ['bullish', 'bearish', 'neutral', 'mixed', 'unknown'];

// 热门媒体段位的固定平台顺序(与 ArticlesTab 一致)
const POPULAR_PLATFORMS: readonly string[] = [
  'weibo', 'weixin', 'xueqiu',
  'eastmoney', 'zhihu', 'toutiao',
  'bilibili', 'douyin', 'xiaohongshu',
];

export interface AdvancedFilterValue {
  risks: Set<string>;
  sentiments: Set<string>;
  mediaTypes: Set<string>;
  industries: Set<string>;
  sources: Set<string>;
  /** 关键词提及范围:'' = 全部,'title' = 仅标题,'body' = 仅正文 */
  keywordScope: '' | 'title' | 'body';
  /** 作者地区:'' = 全部,'domestic' = 境内,'overseas' = 境外(占位,等后端数据) */
  authorRegion: '' | 'domestic' | 'overseas';
  /** 文章类型:'' = 全部,'original' = 原创,'reprint' = 转载(占位,等后端数据) */
  articleType: '' | 'original' | 'reprint';
  topic: string;
  /** 指定媒体名称,逗号分隔(占位,后端缺字段时不参与过滤) */
  specificMedia: string;
  /** 版面名称(占位) */
  column: string;
  /** 指定作者名称(已生效:子串匹配 post.author) */
  authorInput: string;
  startDate: string;  // 'YYYY-MM-DD',空表示不限
  endDate: string;
}

interface Props {
  value: AdvancedFilterValue;
  platforms: SentimentPlatform[];
  axisCounts: { mediaType: Map<string, number>; industry: Map<string, number> };
  sourceCounts: Map<string, number>;
  totalCount: number;
  platformLabel: (code: string) => string;
  onSave: (v: AdvancedFilterValue) => void;
  onCancel: () => void;
  onReset: () => void;
}

function toggle<T>(s: Set<T>, v: T): Set<T> {
  const n = new Set(s);
  if (n.has(v)) n.delete(v); else n.add(v);
  return n;
}

export function AdvancedFilterModal({
  value, platforms, axisCounts, sourceCounts, totalCount,
  platformLabel, onSave, onCancel, onReset,
}: Props) {
  const { t } = useTranslation();

  // draft state — 挂载时从 props 初始化,卸载时丢弃
  const [draftRisks, setDraftRisks] = useState<Set<string>>(() => new Set(value.risks));
  const [draftSent, setDraftSent] = useState<Set<string>>(() => new Set(value.sentiments));
  const [draftSrc, setDraftSrc] = useState<Set<string>>(() => new Set(value.sources));
  const [draftInd, setDraftInd] = useState<Set<string>>(() => new Set(value.industries));
  const [draftMt, setDraftMt] = useState<Set<string>>(() => new Set(value.mediaTypes));
  const [draftTopic, setDraftTopic] = useState<string>(value.topic);
  const [draftKwScope, setDraftKwScope] = useState<'' | 'title' | 'body'>(value.keywordScope);
  const [draftAuthorRegion, setDraftAuthorRegion] = useState<'' | 'domestic' | 'overseas'>(value.authorRegion);
  const [draftArticleType, setDraftArticleType] = useState<'' | 'original' | 'reprint'>(value.articleType);
  const [draftSpecificMedia, setDraftSpecificMedia] = useState<string>(value.specificMedia);
  const [draftColumn, setDraftColumn] = useState<string>(value.column);
  const [draftAuthorInput, setDraftAuthorInput] = useState<string>(value.authorInput);
  const [draftStart, setDraftStart] = useState<string>(value.startDate);
  const [draftEnd, setDraftEnd] = useState<string>(value.endDate);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const startEndError = draftStart && draftEnd && draftStart > draftEnd;

  const handleSave = () => {
    if (startEndError) return;
    onSave({
      risks: draftRisks,
      sentiments: draftSent,
      mediaTypes: draftMt,
      industries: draftInd,
      sources: draftSrc,
      topic: draftTopic,
      keywordScope: draftKwScope,
      authorRegion: draftAuthorRegion,
      articleType: draftArticleType,
      specificMedia: draftSpecificMedia,
      column: draftColumn,
      authorInput: draftAuthorInput,
      startDate: draftStart,
      endDate: draftEnd,
    });
  };

  const handleResetDraft = () => {
    // 本地重置 — 清空所有 draft;不直接 commit 到 parent(用户还可改后再保存)
    setDraftRisks(new Set());
    setDraftSent(new Set());
    setDraftSrc(new Set());
    setDraftInd(new Set());
    setDraftMt(new Set());
    setDraftTopic('');
    setDraftKwScope('');
    setDraftAuthorRegion('');
    setDraftArticleType('');
    setDraftSpecificMedia('');
    setDraftColumn('');
    setDraftAuthorInput('');
    setDraftStart('');
    setDraftEnd('');
    // 同时也调 parent reset 让 rail 状态归零,避免保存时只重置部分
    onReset();
  };

  const node = (
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.45)' }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div
        className="rounded-xl shadow-2xl w-full max-w-6xl max-h-[88vh] flex flex-col"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
      >
        <header className="px-5 py-3 flex items-center justify-between"
          style={{ borderBottom: '1px solid var(--border-color)' }}>
          <h3 className="text-sm font-semibold text-primary">
            {t('dashboard.sentiment.articles.filters.advancedTitle')}
          </h3>
          <button type="button" onClick={onCancel}
            className="text-muted hover:text-primary text-lg leading-none px-2">
            ×
          </button>
        </header>

        {/* 主体:左 filter 行(grow)+ 右 280px 输入栏 */}
        <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_280px] gap-6 px-5 py-4 overflow-y-auto">

          {/* ── 左侧:filter 行 ─────────────────────────────────── */}
          <div className="space-y-3">
            {/* 组 1:媒体维度 */}
            <FilterRow label={t('dashboard.sentiment.articles.filters.mediaType')}>
              <AllOption checked={!draftMt.size} count={totalCount}
                onClick={() => setDraftMt(new Set())} t={t} />
              {MEDIA_TYPE_ORDER.map(mt => {
                const c = axisCounts.mediaType.get(mt) ?? 0;
                const lk = `dashboard.sentiment.articles.mediaTypes.${mt}`;
                const lv = t(lk);
                return (
                  <CheckOption key={mt}
                    label={lv === lk ? mt : lv}
                    count={c}
                    checked={draftMt.has(mt)}
                    onChange={() => setDraftMt(toggle(draftMt, mt))} />
                );
              })}
            </FilterRow>

            <FilterRow label={t('dashboard.sentiment.articles.filters.industry')}>
              <AllOption checked={!draftInd.size} count={totalCount}
                onClick={() => setDraftInd(new Set())} t={t} />
              {INDUSTRY_ORDER.map(ind => {
                const c = axisCounts.industry.get(ind) ?? 0;
                return (
                  <CheckOption key={ind}
                    label={t(`dashboard.sentiment.articles.industries.${ind}`)}
                    count={c}
                    checked={draftInd.has(ind)}
                    onChange={() => setDraftInd(toggle(draftInd, ind))} />
                );
              })}
            </FilterRow>

            <FilterRow label={t('dashboard.sentiment.articles.filters.popular')}>
              <AllOption checked={!draftSrc.size} count={totalCount}
                onClick={() => setDraftSrc(new Set())} t={t} />
              {POPULAR_PLATFORMS
                .filter(c => platforms.some(p => p.code === c))
                .map(code => (
                  <CheckOption key={code}
                    label={platformLabel(code)}
                    count={sourceCounts.get(code) ?? 0}
                    checked={draftSrc.has(code)}
                    onChange={() => setDraftSrc(toggle(draftSrc, code))} />
                ))}
            </FilterRow>

            {/* 虚线分隔 */}
            <div style={{ borderTop: '1px dashed var(--border-color)' }} />

            {/* 组 2:文章内容维度 */}
            <FilterRow label={t('dashboard.sentiment.articles.filters.risk')}>
              <AllOption checked={!draftRisks.size}
                onClick={() => setDraftRisks(new Set())} t={t} />
              {ALL_RISKS.map(r => (
                <CheckOption key={r}
                  label={t(`dashboard.sentiment.articles.risk.${r}`)}
                  checked={draftRisks.has(r)}
                  onChange={() => setDraftRisks(toggle(draftRisks, r))} />
              ))}
            </FilterRow>

            <FilterRow label={t('dashboard.sentiment.articles.filters.sentiment')}>
              <AllOption checked={!draftSent.size}
                onClick={() => setDraftSent(new Set())} t={t} />
              {ALL_SENTIMENTS.map(s => (
                <CheckOption key={s}
                  label={t(`dashboard.sentiment.articles.labels.${s}`)}
                  checked={draftSent.has(s)}
                  onChange={() => setDraftSent(toggle(draftSent, s))} />
              ))}
            </FilterRow>

            {/* 关键词提及 — 单选(全部 / 标题 / 正文) */}
            <FilterRow label={t('dashboard.sentiment.articles.filters.keywordMention')}>
              <AllOption checked={!draftKwScope}
                onClick={() => setDraftKwScope('')} t={t} />
              <CheckOption
                label={t('dashboard.sentiment.articles.filters.titleMention')}
                checked={draftKwScope === 'title'}
                onChange={() => setDraftKwScope(draftKwScope === 'title' ? '' : 'title')} />
              <CheckOption
                label={t('dashboard.sentiment.articles.filters.bodyMention')}
                checked={draftKwScope === 'body'}
                onChange={() => setDraftKwScope(draftKwScope === 'body' ? '' : 'body')} />
            </FilterRow>

            {/* 作者地区 */}
            <FilterRow label={t('dashboard.sentiment.articles.filters.authorRegion')}>
              <AllOption checked={!draftAuthorRegion}
                onClick={() => setDraftAuthorRegion('')} t={t} />
              <CheckOption
                label={t('dashboard.sentiment.articles.filters.authorRegionDomestic')}
                checked={draftAuthorRegion === 'domestic'}
                onChange={() => setDraftAuthorRegion(draftAuthorRegion === 'domestic' ? '' : 'domestic')} />
              <CheckOption
                label={t('dashboard.sentiment.articles.filters.authorRegionOverseas')}
                checked={draftAuthorRegion === 'overseas'}
                onChange={() => setDraftAuthorRegion(draftAuthorRegion === 'overseas' ? '' : 'overseas')} />
            </FilterRow>

            {/* 文章类型 */}
            <FilterRow label={t('dashboard.sentiment.articles.filters.articleType')}>
              <AllOption checked={!draftArticleType}
                onClick={() => setDraftArticleType('')} t={t} />
              <CheckOption
                label={t('dashboard.sentiment.articles.filters.articleTypeOriginal')}
                checked={draftArticleType === 'original'}
                onChange={() => setDraftArticleType(draftArticleType === 'original' ? '' : 'original')} />
              <CheckOption
                label={t('dashboard.sentiment.articles.filters.articleTypeReprint')}
                checked={draftArticleType === 'reprint'}
                onChange={() => setDraftArticleType(draftArticleType === 'reprint' ? '' : 'reprint')} />
            </FilterRow>
          </div>

          {/* ── 右侧:关键字 + 指定媒体 + 版面 + 作者 + 时间 ──────────── */}
          <div className="space-y-3"
            style={{ borderLeft: '1px solid var(--border-color)', paddingLeft: '1.25rem' }}>
            <TextInputRow label={t('dashboard.sentiment.articles.filters.topic')}
              value={draftTopic} onChange={setDraftTopic}
              placeholder={t('dashboard.sentiment.articles.filters.search')} />

            <TextInputRow label={t('dashboard.sentiment.articles.filters.specificMedia')}
              value={draftSpecificMedia} onChange={setDraftSpecificMedia}
              placeholder={t('dashboard.sentiment.articles.filters.specificMediaPlaceholder')} />

            <TextInputRow label={t('dashboard.sentiment.articles.filters.column')}
              value={draftColumn} onChange={setDraftColumn}
              placeholder={t('dashboard.sentiment.articles.filters.columnPlaceholder')} />

            <TextInputRow label={t('dashboard.sentiment.articles.filters.authorInput')}
              value={draftAuthorInput} onChange={setDraftAuthorInput}
              placeholder={t('dashboard.sentiment.articles.filters.authorInputPlaceholder')} />

            <div>
              <label className="block text-xs font-semibold text-primary mb-1.5">
                {t('dashboard.sentiment.articles.filters.timeStart')}
              </label>
              <input type="date" value={draftStart}
                onChange={(e) => setDraftStart(e.target.value)}
                className="w-full px-2 py-1.5 text-xs rounded"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
            </div>

            <div>
              <label className="block text-xs font-semibold text-primary mb-1.5">
                {t('dashboard.sentiment.articles.filters.timeEnd')}
              </label>
              <input type="date" value={draftEnd}
                onChange={(e) => setDraftEnd(e.target.value)}
                className="w-full px-2 py-1.5 text-xs rounded"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
              {startEndError && (
                <p className="text-[11px] mt-1" style={{ color: '#dc2626' }}>
                  {t('dashboard.sentiment.articles.filters.timeRangeError')}
                </p>
              )}
            </div>
          </div>
        </div>

        <footer className="px-5 py-3 flex justify-end gap-2"
          style={{ borderTop: '1px solid var(--border-color)' }}>
          <button type="button" onClick={handleResetDraft}
            className="text-xs px-3 py-1.5 rounded"
            style={{ background: 'transparent', color: 'var(--text-secondary)' }}>
            {t('dashboard.sentiment.articles.filters.reset')}
          </button>
          <button type="button" onClick={onCancel}
            className="text-xs px-3 py-1.5 rounded"
            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-secondary)' }}>
            {t('dashboard.sentiment.articles.filters.cancel')}
          </button>
          <button type="button" onClick={handleSave}
            disabled={!!startEndError}
            className="text-xs px-3 py-1.5 rounded disabled:opacity-50"
            style={{ background: 'var(--accent-primary)', color: '#fff' }}>
            {t('dashboard.sentiment.articles.filters.save')}
          </button>
        </footer>
      </div>
    </div>
  );

  return createPortal(node, document.body);
}

/** 一行筛选 — 左标签 + 右一排 checkbox + AllOption(可换行).贴 image.png 视觉. */
function FilterRow({ label, children }:
  { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6rem_minmax(0,1fr)] gap-3 items-start">
      <div className="text-xs font-semibold text-primary pt-1 text-right pr-1">
        {label}:
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1.5">
        {children}
      </div>
    </div>
  );
}

/** 「全部」chip — 该维度清空选项的快捷.checked = 没有具体勾选时它默认激活. */
function AllOption({ checked, count, onClick, t }:
  { checked: boolean; count?: number; onClick: () => void; t: (k: string) => string }) {
  return (
    <label className="flex items-center gap-1 text-xs cursor-pointer hover:text-primary"
      style={{ color: checked ? 'var(--accent-primary)' : 'var(--text-secondary)' }}
      onClick={(e) => { e.preventDefault(); onClick(); }}
    >
      <input type="checkbox" checked={checked} readOnly
        className="cursor-pointer pointer-events-none" />
      <span className="font-medium">{t('dashboard.sentiment.articles.filters.all')}</span>
      {count !== undefined && <span className="text-[10px] text-muted">{count}</span>}
    </label>
  );
}

/** 右栏常规 text 输入 — 标签上 / input 下 */
function TextInputRow({ label, value, onChange, placeholder }:
  { label: string; value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <div>
      <label className="block text-xs font-semibold text-primary mb-1.5">{label}</label>
      <input type="text" value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-2 py-1.5 text-xs rounded"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
    </div>
  );
}

/** 单个 checkbox 选项 — 含可选计数 */
function CheckOption({ label, count, checked, onChange }:
  { label: string; count?: number; checked: boolean; onChange: () => void }) {
  return (
    <label className="flex items-center gap-1 text-xs cursor-pointer hover:text-primary"
      style={{ color: checked ? 'var(--accent-primary)' : 'var(--text-secondary)' }}>
      <input type="checkbox" checked={checked} onChange={onChange}
        className="cursor-pointer" />
      <span>{label}</span>
      {count !== undefined && (
        <span className="text-[10px] text-muted">{count >= 1000 ? `${(count/1000).toFixed(1)}K` : count}</span>
      )}
    </label>
  );
}
