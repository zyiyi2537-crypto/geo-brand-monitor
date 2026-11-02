// 内容模板抽屉 — 右侧弹出,执行计划编辑器调起.
// 三个 scope tab(系统 / 本租户 / 本主题),每个模板可编辑 / 锁定 / 选用.

import { useEffect, useMemo, useState } from 'react';
import {
  contentTemplatesApi, type ContentTemplate, type TemplateScope,
} from '../../services/contentTemplatesApi';

interface Props {
  open: boolean;
  topicId?: number;
  onClose: () => void;
  // 选用模板回调:把 template 选回给发文表的某一行
  onPick?: (tmpl: ContentTemplate) => void;
}

const SCOPE_TABS: { key: TemplateScope; label: string }[] = [
  { key: 'system', label: '系统' },
  { key: 'tenant', label: '本租户' },
  { key: 'topic',  label: '本主题' },
];

export function TemplateDrawer({ open, topicId, onClose, onPick }: Props) {
  const token = localStorage.getItem('token') || '';
  const [scope, setScope] = useState<TemplateScope>('system');
  const [list, setList] = useState<ContentTemplate[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<ContentTemplate | 'new' | null>(null);

  const refresh = async (s: TemplateScope = scope) => {
    setBusy(true); setErr(null);
    try {
      const rows = await contentTemplatesApi.list(token, {
        scope: s,
        topicId: s === 'topic' ? topicId : undefined,
      });
      setList(rows);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (open) refresh(scope);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, scope, topicId]);

  if (!open) return null;

  return (
    <>
      {/* mask */}
      <div
        className="fixed inset-0 z-40"
        style={{ background: 'rgba(0,0,0,0.35)' }}
        onClick={onClose}
      />
      {/* drawer */}
      <aside
        className="fixed top-0 right-0 z-50 h-full w-[440px] max-w-[92vw] flex flex-col"
        style={{
          background: 'var(--bg-card)',
          borderLeft: '1px solid var(--border-color)',
          boxShadow: '-8px 0 24px rgba(0,0,0,0.18)',
        }}
      >
        <header className="flex items-center justify-between px-4 py-3"
                style={{ borderBottom: '1px solid var(--border-color)' }}>
          <h2 className="text-sm font-semibold text-primary">内容模板</h2>
          <button type="button" onClick={onClose}
                  className="text-muted hover:text-primary text-lg leading-none">×</button>
        </header>

        {/* scope tabs */}
        <div className="flex gap-1 px-3 py-2"
             style={{ borderBottom: '1px solid var(--border-color)' }}>
          {SCOPE_TABS.filter(t => t.key !== 'topic' || topicId).map(t => (
            <button key={t.key} type="button"
                    onClick={() => setScope(t.key)}
                    className="text-xs px-2.5 py-1 rounded-md"
                    style={{
                      background: scope === t.key ? 'var(--accent-primary)' : 'transparent',
                      color: scope === t.key ? '#fff' : 'var(--text-secondary)',
                      border: '1px solid var(--border-color)',
                    }}>
              {t.label}
            </button>
          ))}
          <div className="flex-1" />
          <button type="button"
                  onClick={() => setEditing('new')}
                  className="text-xs px-2.5 py-1 rounded-md"
                  style={{ background: 'var(--accent-primary)', color: '#fff' }}>
            + 新建
          </button>
        </div>

        <div className="flex-1 overflow-auto px-3 py-3 space-y-2">
          {err && (
            <div className="rounded-md p-2 text-xs"
                 style={{ background: 'rgba(239,68,68,0.10)', color: '#ef4444' }}>
              {err}
            </div>
          )}
          {!err && busy && list.length === 0 && (
            <div className="text-xs text-muted py-6 text-center">…</div>
          )}
          {!busy && list.length === 0 && (
            <div className="text-xs text-muted py-6 text-center">暂无模板</div>
          )}
          {list.map(t => (
            <TemplateCard key={t.id} tmpl={t}
                          onEdit={() => setEditing(t)}
                          onLock={async () => {
                            try {
                              await contentTemplatesApi.lock(t.id, token);
                              await refresh();
                            } catch (e: unknown) {
                              setErr(e instanceof Error ? e.message : String(e));
                            }
                          }}
                          onPick={onPick ? () => onPick(t) : undefined} />
          ))}
        </div>
      </aside>

      {editing !== null && (
        <TemplateEditorModal
          mode={editing === 'new' ? 'create' : 'edit'}
          initial={editing === 'new' ? null : editing}
          scope={scope}
          topicId={topicId}
          onCancel={() => setEditing(null)}
          onSaved={async () => { setEditing(null); await refresh(); }}
        />
      )}
    </>
  );
}

function TemplateCard({
  tmpl, onEdit, onLock, onPick,
}: {
  tmpl: ContentTemplate;
  onEdit: () => void;
  onLock: () => void;
  onPick?: () => void;
}) {
  return (
    <div className="rounded-md p-3 text-xs"
         style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border-color)' }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="font-semibold text-primary">{tmpl.name}</span>
          {tmpl.locked && <span title="已锁定">🔒</span>}
        </div>
        <span className="text-[10px] px-1.5 py-0.5 rounded-full"
              style={{ background: 'var(--bg-card)', color: 'var(--text-secondary)' }}>
          {tmpl.kind}
        </span>
      </div>
      <div className="mt-1.5 text-[10px] text-muted">
        长度 {tmpl.length_min}–{tmpl.length_max} 字
        {tmpl.target_platforms.length > 0 && (
          <span className="ml-2">· {tmpl.target_platforms.join(' / ')}</span>
        )}
      </div>
      <div className="mt-2 line-clamp-3 text-muted whitespace-pre-wrap">
        {tmpl.prompt_template}
      </div>
      <div className="mt-2 flex gap-2 justify-end">
        {onPick && (
          <button type="button" onClick={onPick}
                  className="text-[10px] px-2 py-1 rounded-md"
                  style={{ background: 'var(--accent-primary)', color: '#fff' }}>
            使用
          </button>
        )}
        <button type="button" onClick={onEdit}
                className="text-[10px] px-2 py-1 rounded-md"
                style={{ background: 'transparent', color: 'var(--text-secondary)',
                         border: '1px solid var(--border-color)' }}>
          {tmpl.locked ? '查看' : '编辑'}
        </button>
        {!tmpl.locked && (
          <button type="button" onClick={onLock}
                  className="text-[10px] px-2 py-1 rounded-md"
                  style={{ background: 'transparent', color: 'var(--text-secondary)',
                           border: '1px solid var(--border-color)' }}>
            🔒 锁定
          </button>
        )}
      </div>
    </div>
  );
}

const KIND_OPTIONS = ['长文', '短文', 'FAQ', '案例', '测评', '对比', '教程', '问答'];
const PLATFORM_OPTIONS = ['公众号', '小红书', '抖音', '视频号', '知乎', '今日头条', '微博'];

function TemplateEditorModal({
  mode, initial, scope, topicId, onCancel, onSaved,
}: {
  mode: 'create' | 'edit';
  initial: ContentTemplate | null;
  scope: TemplateScope;
  topicId?: number;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const token = localStorage.getItem('token') || '';
  const [name, setName] = useState(initial?.name || '');
  const [kind, setKind] = useState(initial?.kind || '长文');
  const [prompt, setPrompt] = useState(initial?.prompt_template || '');
  const [platforms, setPlatforms] = useState<string[]>(initial?.target_platforms || []);
  const [lenMin, setLenMin] = useState(initial?.length_min ?? 800);
  const [lenMax, setLenMax] = useState(initial?.length_max ?? 1500);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const locked = useMemo(() => initial?.locked === true, [initial]);

  const togglePlat = (p: string) => {
    setPlatforms(s => s.includes(p) ? s.filter(x => x !== p) : [...s, p]);
  };

  const handleSave = async () => {
    if (!name.trim() || !prompt.trim()) {
      setErr('名称和 prompt 都不能为空');
      return;
    }
    setBusy(true); setErr(null);
    try {
      if (mode === 'create') {
        await contentTemplatesApi.create({
          scope, topic_id: scope === 'topic' ? topicId : undefined,
          name, kind, prompt_template: prompt,
          target_platforms: platforms,
          length_min: lenMin, length_max: lenMax,
        }, token);
      } else if (initial) {
        await contentTemplatesApi.update(initial.id, {
          name,
          ...(locked ? {} : { kind, prompt_template: prompt }),
          target_platforms: platforms,
          length_min: lenMin, length_max: lenMax,
        }, token);
      }
      onSaved();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center px-4"
         style={{ background: 'rgba(0,0,0,0.45)' }}>
      <div className="w-[560px] max-w-full rounded-md p-4"
           style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-primary">
            {mode === 'create' ? '新建模板' : (locked ? '查看模板 🔒' : '编辑模板')}
          </h3>
          <button type="button" onClick={onCancel}
                  className="text-muted hover:text-primary text-lg leading-none">×</button>
        </div>

        {err && (
          <div className="rounded-md p-2 mb-3 text-xs"
               style={{ background: 'rgba(239,68,68,0.10)', color: '#ef4444' }}>
            {err}
          </div>
        )}

        <div className="space-y-3 text-xs">
          <div>
            <label className="block text-muted mb-1">名称</label>
            <input className="w-full rounded-md px-2 py-1.5"
                   style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                            border: '1px solid var(--border-color)' }}
                   value={name} onChange={e => setName(e.target.value)} />
          </div>

          <div className="flex gap-3">
            <div className="flex-1">
              <label className="block text-muted mb-1">类型</label>
              <select className="w-full rounded-md px-2 py-1.5"
                      style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                               border: '1px solid var(--border-color)' }}
                      value={kind}
                      disabled={locked}
                      onChange={e => setKind(e.target.value)}>
                {KIND_OPTIONS.map(k => <option key={k}>{k}</option>)}
              </select>
            </div>
            <div className="w-24">
              <label className="block text-muted mb-1">最短</label>
              <input type="number" className="w-full rounded-md px-2 py-1.5"
                     style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                              border: '1px solid var(--border-color)' }}
                     value={lenMin} onChange={e => setLenMin(Number(e.target.value) || 0)} />
            </div>
            <div className="w-24">
              <label className="block text-muted mb-1">最长</label>
              <input type="number" className="w-full rounded-md px-2 py-1.5"
                     style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                              border: '1px solid var(--border-color)' }}
                     value={lenMax} onChange={e => setLenMax(Number(e.target.value) || 0)} />
            </div>
          </div>

          <div>
            <label className="block text-muted mb-1">适用平台</label>
            <div className="flex flex-wrap gap-1.5">
              {PLATFORM_OPTIONS.map(p => (
                <button key={p} type="button"
                        onClick={() => togglePlat(p)}
                        className="text-[10px] px-2 py-1 rounded-md"
                        style={{
                          background: platforms.includes(p) ? 'var(--accent-primary)' : 'transparent',
                          color: platforms.includes(p) ? '#fff' : 'var(--text-secondary)',
                          border: '1px solid var(--border-color)',
                        }}>
                  {p}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="block text-muted mb-1">
              Prompt 模板{locked && <span className="ml-1 text-[10px]">🔒 已锁定,不可改</span>}
            </label>
            <textarea className="w-full rounded-md px-2 py-1.5 font-mono"
                      style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                               border: '1px solid var(--border-color)',
                               minHeight: 180, fontSize: 12 }}
                      value={prompt}
                      disabled={locked}
                      onChange={e => setPrompt(e.target.value)} />
            <div className="text-[10px] text-muted mt-1">
              占位符:{'{{query}} {{brand}} {{industry}} {{platform}} {{length_min}} {{length_max}} {{brand_block}}'}
            </div>
          </div>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'transparent', color: 'var(--text-secondary)',
                           border: '1px solid var(--border-color)' }}>
            取消
          </button>
          <button type="button" onClick={handleSave} disabled={busy}
                  className="text-xs px-3 py-1.5 rounded-md text-white"
                  style={{ background: 'var(--accent-primary)', opacity: busy ? 0.5 : 1 }}>
            {busy ? '…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}
