// 发文计划编辑器 — draft 态全功能编辑;confirmed 态用插入式编辑(同组件,提交不退回 draft).
// 增删行 / 改日期 / 改 query / 选模板(从抽屉里选) / 选平台 / 备注 / ↑↓ 调序.

import { useEffect, useMemo, useState } from 'react';
import {
  adminReviewApi, type ExecutionPlan, type PlanItemDraft, type PublishPlanItem,
} from '../../services/adminReviewApi';
import {
  contentTemplatesApi, type ContentTemplate,
} from '../../services/contentTemplatesApi';
import { TemplateDrawer } from './TemplateDrawer';

type RowDraft = {
  id?: string;           // 老行带后端 uuid,新行先空,提交时补
  localKey: string;      // 行内 React key — 永远稳定
  seq: number;
  publish_date: string;
  // seed-based 新流程:seed 非空,query 留空;legacy:query ∈ monitored,seed 为空.
  // 二选一,至少有一个非空.
  seed: string;
  query: string;
  // 2026-06-11 — 多选监测 query(legacy 单 query 行加载时并入这里)
  queries: string[];
  template_id: number | null;
  platform: string;
  note: string;
  // 2026-05-28 — 单行 combo override(空 → 用画像默认)
  creation_directions: string[];
  copywriting_types: string[];
};

// 2026-05-28 — combo 候选值与 BrandProfileForm 同步
const COMBO_DIRECTIONS: { value: string; label: string }[] = [
  { value: 'industry_insight', label: '行业洞察' },
  { value: 'case_story',       label: '案例分享' },
  { value: 'how_to_guide',     label: '实操指南' },
  { value: 'trend_forecast',   label: '趋势预测' },
  { value: 'product_review',   label: '产品评测' },
  { value: 'customer_story',   label: '客户故事' },
  { value: 'faq',              label: 'FAQ' },
];
const COMBO_TYPES: { value: string; label: string }[] = [
  { value: 'long_form',          label: '深度长文' },
  { value: 'medium_post',        label: '中等图文' },
  { value: 'short_social',       label: '短社媒' },
  { value: 'video_script_long',  label: '长视频脚本' },
  { value: 'video_script_short', label: '短视频文案' },
  { value: 'faq_list',           label: 'FAQ 列表' },
];

const todayISO = () => new Date().toISOString().slice(0, 10);

const addDays = (iso: string, days: number): string => {
  const d = new Date(iso + 'T00:00:00');
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

const fromPlanItem = (it: PublishPlanItem): RowDraft => ({
  id: it.id,
  localKey: it.id,
  seq: it.seq,
  publish_date: it.publish_date,
  seed: it.seed || '',
  query: it.query,
  // legacy 单 query 行并入 queries 多选;两者都有时 queries 优先
  queries: (it.queries && it.queries.length > 0) ? it.queries : (it.query ? [it.query] : []),
  template_id: it.template_id ?? null,
  platform: it.platform || '',
  note: it.note || '',
  creation_directions: it.creation_directions || [],
  copywriting_types: it.copywriting_types || [],
});

interface Props {
  plan: ExecutionPlan;
  topicId: number;
  // confirmed 态下的「插入式编辑」走这个回调;draft 态用 onConfirmed
  mode: 'draft' | 'inline-edit';
  onSaved: (updated: ExecutionPlan) => void;       // 保存草稿 / 保存修改 都走它
  onConfirmed?: (updated: ExecutionPlan) => void;  // draft → confirmed
  onCancel?: () => void;                           // inline-edit 模式下的取消按钮
}

export function PublishingPlanEditor({
  plan, topicId, mode, onSaved, onConfirmed, onCancel,
}: Props) {
  const token = localStorage.getItem('token') || '';
  const monitored = plan.monitored_queries || [];

  const [rows, setRows] = useState<RowDraft[]>(() =>
    [...plan.publishing_plan].sort((a, b) => a.seq - b.seq).map(fromPlanItem),
  );
  const [templates, setTemplates] = useState<ContentTemplate[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // 2026-06-12 — 行编辑统一弹窗(日期/种子/监测问题/模板/平台/备注/创作偏好都在里面),
  // 表格本体只读紧凑展示。记录正在编辑哪一行(localKey)。
  const [editKey, setEditKey] = useState<string | null>(null);
  const [drawerTarget, setDrawerTarget] = useState<string | null>(null); // localKey of row
  const [savingDraft, setSavingDraft] = useState(false);
  const [savingConfirm, setSavingConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;
  // 总页数随 rows 变化;在最后一页删行 / 切到非空 page 时回缩.
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  // 2026-05-31 — 按 seed 聚合折叠.同一 seed 下的多个 (模板 × 平台) 行折成一组;
  // 空 seed 行进「(legacy / 无种子)」组.默认所有组展开,用户点 ▼ 折叠.
  const [collapsedSeeds, setCollapsedSeeds] = useState<Set<string>>(new Set());
  const toggleSeed = (key: string) => {
    setCollapsedSeeds(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };
  // 是否启用聚合视图.≥2 个不同 seed 才启用,否则平铺更直观.
  const seedGroups = useMemo(() => {
    const m = new Map<string, RowDraft[]>();
    for (const r of rows) {
      const key = r.seed.trim() || '(无种子 / legacy)';
      if (!m.has(key)) m.set(key, []);
      m.get(key)!.push(r);
    }
    return m;
  }, [rows]);
  const groupedMode = seedGroups.size >= 2;

  // 拉一次模板全集,row 的下拉用;抽屉里改了再 refresh
  const refreshTemplates = async () => {
    try {
      const [sys, tenant, topic] = await Promise.all([
        contentTemplatesApi.list(token, { scope: 'system' }),
        contentTemplatesApi.list(token, { scope: 'tenant' }),
        contentTemplatesApi.list(token, { scope: 'topic', topicId }),
      ]);
      setTemplates([...sys, ...tenant, ...topic]);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };
  useEffect(() => { refreshTemplates(); }, []);

  const tmplById = useMemo(() => {
    const m = new Map<number, ContentTemplate>();
    for (const t of templates) m.set(t.id, t);
    return m;
  }, [templates]);

  const newRow = (): RowDraft => {
    const last = rows[rows.length - 1];
    const date = last ? addDays(last.publish_date, 1) : todayISO();
    const defaultTmpl = templates.find(t => t.scope === 'system') || templates[0];
    const defaultPlat = defaultTmpl?.target_platforms?.[0] || '公众号';
    const localKey = `new-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    // 新版默认 seed-based:种子优先,query 留空(运营手填种子文本).
    // 老 legacy 行管理员若想加,把 query 切到 monitored 列表中.
    return {
      id: undefined,
      localKey,
      seq: rows.length,
      publish_date: date,
      seed: last?.seed || '',
      query: '',
      queries: [],
      template_id: defaultTmpl ? defaultTmpl.id : null,
      platform: defaultPlat,
      note: '',
      creation_directions: [],
      copywriting_types: [],
    };
  };

  const updateRow = (key: string, patch: Partial<RowDraft>) => {
    setRows(rs => rs.map(r => r.localKey === key ? { ...r, ...patch } : r));
  };

  const removeRow = (key: string) => {
    setRows(rs => rs.filter(r => r.localKey !== key).map((r, i) => ({ ...r, seq: i })));
  };

  const moveRow = (key: string, dir: -1 | 1) => {
    setRows(rs => {
      const idx = rs.findIndex(r => r.localKey === key);
      if (idx < 0) return rs;
      const tgt = idx + dir;
      if (tgt < 0 || tgt >= rs.length) return rs;
      const next = rs.slice();
      [next[idx], next[tgt]] = [next[tgt], next[idx]];
      return next.map((r, i) => ({ ...r, seq: i }));
    });
  };

  const validate = (): PlanItemDraft[] | null => {
    if (rows.length === 0) {
      setErr('发文表为空,请至少添加一行');
      return null;
    }
    const monSet = new Set(monitored);
    const drafts: PlanItemDraft[] = [];
    for (const r of rows) {
      const seed = r.seed.trim();
      const queries = r.queries.map(q => q.trim()).filter(Boolean);
      if (!seed && queries.length === 0) {
        setErr(`第 ${r.seq + 1} 行种子和监测问题至少要填一个`);
        return null;
      }
      const badQ = queries.find(q => !monSet.has(q));
      if (badQ) {
        setErr(`第 ${r.seq + 1} 行监测问题不在监测列表里:${badQ}`);
        return null;
      }
      if (!r.template_id) {
        setErr(`第 ${r.seq + 1} 行没选模板`);
        return null;
      }
      if (!r.platform) {
        setErr(`第 ${r.seq + 1} 行没选平台`);
        return null;
      }
      drafts.push({
        id: r.id || null,
        seq: r.seq,
        publish_date: r.publish_date,
        seed: seed || null,
        // legacy 单值字段:无 seed 的纯 query 行回填第一条,保老后端/老数据兼容
        query: (!seed && queries.length > 0) ? queries[0] : '',
        queries,
        template_id: r.template_id,
        platform: r.platform,
        note: r.note || null,
        creation_directions: r.creation_directions,
        copywriting_types: r.copywriting_types,
      });
    }
    return drafts;
  };

  const handleSaveDraft = async () => {
    const drafts = validate();
    if (!drafts) return;
    setSavingDraft(true); setErr(null);
    try {
      const updated = await adminReviewApi.updateExecutionPlan(topicId, drafts, token);
      onSaved(updated);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingDraft(false);
    }
  };

  const handleConfirm = async () => {
    const drafts = validate();
    if (!drafts) return;
    setSavingConfirm(true); setErr(null);
    try {
      await adminReviewApi.updateExecutionPlan(topicId, drafts, token);
      const updated = await adminReviewApi.confirmExecutionPlan(topicId, token);
      onConfirmed?.(updated);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingConfirm(false);
    }
  };

  return (
    <div className="space-y-3">
      <header className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-primary">
          发文计划({mode === 'draft' ? '草稿' : '编辑中'} · {rows.length} 篇)
        </h2>
        <div className="flex-1" />
        <button type="button"
                onClick={() => { setDrawerTarget(null); setDrawerOpen(true); }}
                className="text-xs px-2.5 py-1 rounded-md"
                style={{ background: 'transparent', color: 'var(--text-secondary)',
                         border: '1px solid var(--border-color)' }}>
          📋 模板抽屉
        </button>
        <button type="button"
                onClick={() => {
                  setRows(rs => {
                    const next = [...rs, newRow()];
                    // 新行落到末页 — 调用方 setPage 在下个 tick 跑,直接按 next.length 算
                    setPage(Math.max(1, Math.ceil(next.length / PAGE_SIZE)));
                    return next;
                  });
                }}
                className="text-xs px-2.5 py-1 rounded-md"
                style={{ background: 'var(--accent-primary)', color: '#fff' }}>
          + 添加一行
        </button>
      </header>

      {err && (
        <div className="rounded-md p-2 text-xs"
             style={{ background: 'rgba(239,68,68,0.10)', color: '#ef4444' }}>
          {err}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ color: 'var(--text-muted)' }}>
              <th className="py-2 px-2 text-left">#</th>
              <th className="py-2 px-2 text-left">日期</th>
              <th className="py-2 px-2 text-left">种子</th>
              <th className="py-2 px-2 text-left">监测问题</th>
              <th className="py-2 px-2 text-left">命中%</th>
              <th className="py-2 px-2 text-left">模板</th>
              <th className="py-2 px-2 text-left">平台</th>
              <th className="py-2 px-2 text-left">备注</th>
              <th className="py-2 px-2 text-center">操作</th>
            </tr>
          </thead>
          <tbody>
            {(() => {
              // 2026-06-12 — 行=只读紧凑文本,点行(或 ✎)打开统一编辑弹窗;不再行内展开.
              const renderItem = (r: RowDraft, globalIdx: number): React.ReactNode[] => {
                const tmpl = r.template_id ? tmplById.get(r.template_id) : null;
                const orig = plan.publishing_plan.find(x => x.id === r.id);
                const cov = orig?.coverage_pct ?? 0;
                const tint = cov === 0 ? 'rgba(239,68,68,0.06)'
                  : cov < 50 ? 'rgba(234,179,8,0.06)' : 'rgba(16,185,129,0.06)';
                const comboN = r.creation_directions.length + r.copywriting_types.length;
                return [
                  <tr key={r.localKey}
                      onClick={() => setEditKey(r.localKey)}
                      style={{
                        background: tint,
                        borderTop: '1px solid var(--border-color)',
                        cursor: 'pointer',
                      }}>
                    <td className="py-2 px-2 tabular-nums text-muted whitespace-nowrap">
                      <span className="inline-flex items-center gap-1">
                        {globalIdx + 1}
                        <span className="inline-flex flex-col">
                          <button type="button" onClick={(e) => {
                            e.stopPropagation();
                            moveRow(r.localKey, -1);
                            if (!groupedMode && globalIdx % PAGE_SIZE === 0 && page > 1) setPage(p => p - 1);
                          }}
                                  className="text-[9px] leading-none text-muted hover:text-primary">▲</button>
                          <button type="button" onClick={(e) => {
                            e.stopPropagation();
                            moveRow(r.localKey, 1);
                            if (!groupedMode && globalIdx % PAGE_SIZE === PAGE_SIZE - 1 && page < totalPages) setPage(p => p + 1);
                          }}
                                  className="text-[9px] leading-none text-muted hover:text-primary">▼</button>
                        </span>
                      </span>
                    </td>
                    <td className="py-2 px-2 tabular-nums text-primary whitespace-nowrap">
                      {r.publish_date || <span className="text-muted">—</span>}
                    </td>
                    <td className="py-2 px-2 max-w-[220px]">
                      <div className="truncate text-primary" title={r.seed}>
                        {r.seed || <span className="text-muted">—</span>}
                      </div>
                    </td>
                    <td className="py-2 px-2 whitespace-nowrap"
                        title={r.queries.join('\n')}>
                      {r.queries.length > 0 ? (
                        <span className="text-primary">{r.queries.length} 条</span>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </td>
                    <td className="py-2 px-2 tabular-nums whitespace-nowrap">
                      <span style={{ color: cov === 0 ? '#ef4444' : cov < 50 ? '#eab308' : '#10b981' }}>
                        {cov.toFixed(1)}%
                      </span>
                    </td>
                    <td className="py-2 px-2 max-w-[140px]">
                      <div className="truncate" style={{ color: 'var(--text-secondary)' }}
                           title={tmpl?.name}>
                        {tmpl?.name || <span className="text-muted">未选</span>}
                      </div>
                    </td>
                    <td className="py-2 px-2 whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>
                      {r.platform || <span className="text-muted">—</span>}
                    </td>
                    <td className="py-2 px-2 max-w-[120px]">
                      <div className="truncate text-muted" title={r.note}>
                        {r.note}
                        {comboN > 0 && (
                          <span className="ml-1 text-[10px]" style={{ color: 'var(--accent-primary)' }}
                                title="本行自定义了创作偏好">偏好×{comboN}</span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 px-2 text-center whitespace-nowrap">
                      <button type="button"
                              onClick={(e) => { e.stopPropagation(); setEditKey(r.localKey); }}
                              className="text-xs px-1.5 py-0.5 rounded-md mr-1"
                              style={{ color: 'var(--text-secondary)' }}
                              title="编辑本行">✎</button>
                      <button type="button" onClick={(e) => { e.stopPropagation(); removeRow(r.localKey); }}
                              className="text-muted hover:text-primary" title="删除本行">×</button>
                    </td>
                  </tr>,
                ];
              };

              // 2026-05-31 — 多 seed 时按 seed 聚合;**保留分页**(按行分页),
              // 当前页 slice 内按 seed 二次分组.同 seed 的 items 跨页时,
              // header 在每一页该 seed 出现处都重画一次,告诉用户"这是该 seed 的延续部分".
              if (groupedMode) {
                const out: React.ReactNode[] = [];
                const slice = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
                // 当前 slice 按 seed 分组(保 input order)
                const sliceGroups = new Map<string, RowDraft[]>();
                for (const r of slice) {
                  const key = r.seed.trim() || '(无种子 / legacy 行)';
                  if (!sliceGroups.has(key)) sliceGroups.set(key, []);
                  sliceGroups.get(key)!.push(r);
                }
                let inPageIdx = 0;
                for (const [seedKey, items] of sliceGroups) {
                  const collapsed = collapsedSeeds.has(seedKey);
                  const isLegacy = seedKey.startsWith('(无种子');
                  // 该 seed 在全表的总篇数(给 header 显示 "10 篇" 用,跟当前页区分)
                  const totalInSeed = seedGroups.get(seedKey)?.length || items.length;
                  out.push(
                    <tr key={`seed:${seedKey}:page${page}`}
                        onClick={() => toggleSeed(seedKey)}
                        style={{
                          background: 'var(--bg-secondary)',
                          borderTop: '2px solid var(--border-color)',
                          cursor: 'pointer',
                        }}>
                      <td colSpan={9} className="py-2 px-2">
                        <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                          {collapsed ? '▶' : '▼'}
                        </span>
                        <span className="ml-2 font-semibold" style={{
                          color: isLegacy ? 'var(--text-muted)' : 'var(--accent-primary)',
                        }}>
                          {isLegacy ? '无种子 / legacy 行' : `种子: ${seedKey}`}
                        </span>
                        <span className="ml-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                          · {items.length} 篇(本页) / {totalInSeed} 篇(总计)
                        </span>
                      </td>
                    </tr>
                  );
                  if (!collapsed) {
                    for (const r of items) {
                      const globalIdx = (page - 1) * PAGE_SIZE + inPageIdx;
                      out.push(...renderItem(r, globalIdx));
                      inPageIdx++;
                    }
                  } else {
                    inPageIdx += items.length;
                  }
                }
                return out;
              }

              // flat 模式:原老逻辑(单 seed 或全 legacy)
              const out: React.ReactNode[] = [];
              const slice = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
              slice.forEach((r, i) => {
                out.push(...renderItem(r, (page - 1) * PAGE_SIZE + i));
              });
              return out;
            })()}
          </tbody>
        </table>
      </div>

      {rows.length > PAGE_SIZE && (
        <div className="flex items-center justify-between text-xs text-secondary pt-1">
          <span className="tabular-nums text-muted">
            {(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, rows.length)} / {rows.length} 篇
          </span>
          <div className="flex items-center gap-2">
            <button type="button" disabled={page <= 1}
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    className="px-2 py-1 rounded-md disabled:opacity-40"
                    style={{ background: 'var(--bg-tertiary)' }}>
              上一页
            </button>
            <span className="tabular-nums">{page} / {totalPages}</span>
            <button type="button" disabled={page >= totalPages}
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    className="px-2 py-1 rounded-md disabled:opacity-40"
                    style={{ background: 'var(--bg-tertiary)' }}>
              下一页
            </button>
          </div>
        </div>
      )}

      <p className="text-[10px] text-muted">
        同一 Query 可排多行(不同时间 / 不同平台)。命中率 0% 行底色浅红,&lt;50% 浅黄,≥50% 浅绿。
      </p>

      <div className="flex justify-end gap-2">
        {onCancel && (
          <button type="button" onClick={onCancel}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'transparent', color: 'var(--text-secondary)',
                           border: '1px solid var(--border-color)' }}>
            取消
          </button>
        )}
        <button type="button" onClick={handleSaveDraft} disabled={savingDraft || savingConfirm}
                className="text-xs px-3 py-1.5 rounded-md"
                style={{ background: 'transparent', color: 'var(--text-secondary)',
                         border: '1px solid var(--border-color)',
                         opacity: savingDraft || savingConfirm ? 0.5 : 1 }}>
          {savingDraft ? '保存中…' : (mode === 'draft' ? '💾 保存草稿' : '💾 保存修改')}
        </button>
        {mode === 'draft' && (
          <button type="button" onClick={handleConfirm} disabled={savingDraft || savingConfirm}
                  className="text-xs px-3 py-1.5 rounded-md text-white"
                  style={{ background: 'var(--accent-primary)',
                           opacity: savingDraft || savingConfirm ? 0.5 : 1 }}>
            {savingConfirm ? '生成中…' : '✅ 确认并生成文章 →'}
          </button>
        )}
      </div>

      <TemplateDrawer open={drawerOpen} topicId={topicId}
                      onClose={() => { setDrawerOpen(false); setDrawerTarget(null); refreshTemplates(); }}
                      onPick={drawerTarget ? (t) => {
                        const plat = t.target_platforms[0] || '';
                        updateRow(drawerTarget, { template_id: t.id, platform: plat });
                        setDrawerOpen(false);
                        setDrawerTarget(null);
                        refreshTemplates();
                      } : undefined} />

      {editKey && (() => {
        const row = rows.find(x => x.localKey === editKey);
        if (!row) return null;
        return (
          <RowEditModal
            row={row}
            monitored={monitored}
            templates={templates}
            tmplById={tmplById}
            onPatch={patch => updateRow(editKey, patch)}
            onClose={() => setEditKey(null)}
          />
        );
      })()}
    </div>
  );
}


// 2026-06-12 — 行编辑统一弹窗:一行的所有字段都在这里改,即改即生效,关掉即完成.
function RowEditModal({
  row, monitored, templates, tmplById, onPatch, onClose,
}: {
  row: RowDraft;
  monitored: string[];
  templates: ContentTemplate[];
  tmplById: Map<number, ContentTemplate>;
  onPatch: (patch: Partial<RowDraft>) => void;
  onClose: () => void;
}) {
  const [filter, setFilter] = useState('');
  const pickedSet = useMemo(() => new Set(row.queries), [row.queries]);
  const shown = useMemo(() => {
    const f = filter.trim().toLowerCase();
    return f ? monitored.filter(q => q.toLowerCase().includes(f)) : monitored;
  }, [monitored, filter]);
  const toggleQuery = (q: string) => {
    onPatch({
      queries: pickedSet.has(q) ? row.queries.filter(x => x !== q) : [...row.queries, q],
    });
  };
  const tmpl = row.template_id ? tmplById.get(row.template_id) : null;
  const platOpts = tmpl?.target_platforms?.length
    ? tmpl.target_platforms
    : ['公众号', '小红书', '抖音', '视频号'];

  const inputStyle = {
    background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
    border: '1px solid var(--border-color)',
  } as const;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4"
         style={{ background: 'rgba(0,0,0,0.45)' }}
         onClick={onClose}>
      <div className="w-[640px] max-w-full rounded-md p-4 flex flex-col gap-3"
           style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                    maxHeight: '85vh' }}
           onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-primary">编辑发文行(#{row.seq + 1})</h3>
          <button type="button" onClick={onClose}
                  className="text-muted hover:text-primary text-lg leading-none">×</button>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <label className="block text-muted mb-1">发布日期</label>
            <input type="date" className="w-full rounded-md px-2 py-1.5" style={inputStyle}
                   value={row.publish_date}
                   onChange={e => onPatch({ publish_date: e.target.value })} />
          </div>
          <div>
            <label className="block text-muted mb-1">种子提示词</label>
            <input type="text" className="w-full rounded-md px-2 py-1.5" style={inputStyle}
                   placeholder="种子提示词文本…"
                   value={row.seed}
                   onChange={e => onPatch({ seed: e.target.value })} />
          </div>
          <div>
            <label className="block text-muted mb-1">内容模板</label>
            <select className="w-full rounded-md px-2 py-1.5" style={inputStyle}
                    value={row.template_id || ''}
                    onChange={e => {
                      const newId = Number(e.target.value) || null;
                      const nt = newId ? tmplById.get(newId) : null;
                      const newPlat = (nt && nt.target_platforms.length && !nt.target_platforms.includes(row.platform))
                        ? nt.target_platforms[0]
                        : row.platform;
                      onPatch({ template_id: newId, platform: newPlat });
                    }}>
              <option value="">—</option>
              {templates.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-muted mb-1">发布平台</label>
            <select className="w-full rounded-md px-2 py-1.5" style={inputStyle}
                    value={row.platform}
                    onChange={e => onPatch({ platform: e.target.value })}>
              {platOpts.map(p => <option key={p}>{p}</option>)}
            </select>
          </div>
        </div>

        <div className="flex flex-col gap-1.5 min-h-0">
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted">监测问题(本文需自然覆盖)</label>
            <span className="text-xs text-muted">已选 {row.queries.length}</span>
            {row.queries.length > 0 && (
              <button type="button" onClick={() => onPatch({ queries: [] })}
                      className="text-[11px] px-1.5 py-0.5 rounded-md"
                      style={{ color: 'var(--text-secondary)',
                               border: '1px solid var(--border-color)' }}>
                清空
              </button>
            )}
            <div className="flex-1" />
            <input type="text" value={filter} onChange={e => setFilter(e.target.value)}
                   placeholder="过滤…"
                   className="w-[160px] rounded-md px-2 py-1 text-xs" style={inputStyle} />
          </div>
          <div className="overflow-y-auto rounded-md"
               style={{ border: '1px solid var(--border-color)', maxHeight: 200 }}>
            {shown.length === 0 ? (
              <div className="p-3 text-center text-xs text-muted">无匹配的监测问题</div>
            ) : shown.map(q => (
              <label key={q}
                     className="flex items-start gap-2 px-3 py-1.5 text-xs cursor-pointer"
                     style={{ borderBottom: '1px solid var(--border-color)',
                              color: 'var(--text-primary)' }}>
                <input type="checkbox" checked={pickedSet.has(q)}
                       onChange={() => toggleQuery(q)} className="mt-0.5 shrink-0" />
                <span>{q}</span>
              </label>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs text-muted mb-1">备注</label>
          <input type="text" className="w-full rounded-md px-2 py-1.5 text-xs" style={inputStyle}
                 placeholder="备注…"
                 value={row.note}
                 onChange={e => onPatch({ note: e.target.value })} />
        </div>

        <div>
          <div className="text-[11px] text-muted mb-1.5">
            自定义本行创作偏好(空则用画像默认;非空则只用本行勾的)
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <ChipMultiSelect
              label={`创作方向(${row.creation_directions.length})`}
              options={COMBO_DIRECTIONS}
              value={row.creation_directions}
              onChange={v => onPatch({ creation_directions: v })}
            />
            <ChipMultiSelect
              label={`文案类型(${row.copywriting_types.length})`}
              options={COMBO_TYPES}
              value={row.copywriting_types}
              onChange={v => onPatch({ copywriting_types: v })}
            />
          </div>
        </div>

        <div className="flex justify-end">
          <button type="button" onClick={onClose}
                  className="px-4 py-1.5 text-xs rounded-md text-white"
                  style={{ background: 'var(--accent-primary)' }}>
            完成
          </button>
        </div>
      </div>
    </div>
  );
}


// 2026-05-28 — 小型 chip 多选,行内 combo override 用.
function ChipMultiSelect({
  label, options, value, onChange,
}: {
  label: string;
  options: { value: string; label: string }[];
  value: string[];
  onChange: (v: string[]) => void;
}) {
  const set = new Set(value || []);
  const toggle = (v: string) => {
    const n = new Set(set);
    if (n.has(v)) n.delete(v); else n.add(v);
    onChange(Array.from(n));
  };
  return (
    <div>
      <div className="text-[11px] mb-1" style={{ color: 'var(--text-secondary)' }}>{label}</div>
      <div className="flex flex-wrap gap-1">
        {options.map(opt => {
          const checked = set.has(opt.value);
          return (
            <button
              key={opt.value} type="button"
              onClick={(e) => { e.stopPropagation(); toggle(opt.value); }}
              className="px-2 py-0.5 rounded-full text-[10px]"
              style={{
                background: checked ? 'var(--accent-primary)' : 'var(--bg-card)',
                color: checked ? '#fff' : 'var(--text-secondary)',
                border: '1px solid var(--border-color)',
              }}
            >
              {checked && '✓ '}{opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
