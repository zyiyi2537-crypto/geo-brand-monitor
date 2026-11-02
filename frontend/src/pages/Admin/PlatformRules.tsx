// 平台审核规则库 — admin 维护各发布平台的"审核红线",生成文章时按平台注入 prompt。
// 左侧平台列表(带拒稿计数),右侧规则编辑器 + AI 初稿 + 待采纳增量(从拒稿学习产出)。

import { useCallback, useEffect, useState } from 'react';
import { platformRulesApi, type PlatformRule } from '../../services/platformRulesApi';

const card: React.CSSProperties = {
  background: 'var(--bg-card)', border: '1px solid var(--border-color)',
};
const inputStyle: React.CSSProperties = {
  background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
  border: '1px solid var(--border-color)',
};

export function AdminPlatformRules() {
  const token = localStorage.getItem('token') || '';
  const [rules, setRules] = useState<PlatformRule[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [draft, setDraft] = useState('');           // 当前编辑框内容
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);  // 'save' | 'seed' | 'learn' | 'approve'
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const reload = useCallback(async (keepActive = true) => {
    try {
      const list = await platformRulesApi.list(token);
      setRules(list);
      setErr(null);
      if (!keepActive || !active) {
        const first = list[0]?.platform || null;
        setActive(a => (keepActive && a) ? a : first);
      }
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  }, [token, active]);

  useEffect(() => { reload(false);   }, []);

  const current = rules.find(r => r.platform === active) || null;

  // 切平台 → 编辑框装载该平台规则
  useEffect(() => {
    setDraft(current?.rules_text || '');
    setDirty(false);
    setMsg(null);
  }, [active, current?.rules_text]);

  const run = async (key: string, fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(key); setErr(null); setMsg(null);
    try { await fn(); } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally { setBusy(null); }
  };

  const save = () => run('save', async () => {
    if (!active) return;
    const updated = await platformRulesApi.update(active, draft, token);
    setRules(rs => rs.map(r => r.platform === updated.platform ? updated : r));
    setDirty(false);
    setMsg('已保存,后续生成的文章将遵守这份规则');
  });

  const seed = () => run('seed', async () => {
    if (!active) return;
    const { draft: d } = await platformRulesApi.seed(active, token);
    setDraft(prev => prev.trim() ? `${prev.trim()}\n${d}` : d);
    setDirty(true);
    setMsg('AI 初稿已填入编辑框,请校对后点保存');
  });

  const learn = () => run('learn', async () => {
    const updated = await platformRulesApi.learn(token);
    setRules(rs => rs.map(r => updated.find(u => u.platform === r.platform) || r));
    setMsg(`已从拒稿学习:${updated.map(u => u.platform).join('、')} 产出待采纳增量`);
  });

  const approve = () => run('approve', async () => {
    if (!active) return;
    const updated = await platformRulesApi.approvePending(active, token);
    setRules(rs => rs.map(r => r.platform === updated.platform ? updated : r));
    setMsg('增量已并入规则并生效');
  });

  const dismissPending = () => run('save', async () => {
    if (!active || !current) return;
    const updated = await platformRulesApi.update(active, current.rules_text, token, true);
    setRules(rs => rs.map(r => r.platform === updated.platform ? updated : r));
    setMsg('已忽略本次增量');
  });

  const totalRejected = rules.reduce((s, r) => s + r.rejected_count, 0);

  return (
    <div className="max-w-[1100px] mx-auto p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-primary">平台审核规则</h1>
          <p className="text-xs text-muted mt-1">
            每个发布平台一份审核红线,生成文章时自动注入;回填的平台拒稿原因可一键提炼成规则增量。
          </p>
        </div>
        <button type="button" disabled={busy !== null || totalRejected === 0}
                onClick={learn}
                title={totalRejected === 0 ? '还没有已回填的平台拒稿原因(在内容审核详情里回填)' : ''}
                className="text-xs px-3 py-1.5 rounded-md text-white disabled:opacity-40"
                style={{ background: 'var(--accent-primary)' }}>
          {busy === 'learn' ? '学习中…' : `🧠 从拒稿学习(素材 ${totalRejected} 条)`}
        </button>
      </div>

      {err && (
        <div className="rounded-md p-2 mb-3 text-xs"
             style={{ background: 'rgba(239,68,68,0.10)', color: '#ef4444' }}>{err}</div>
      )}
      {msg && (
        <div className="rounded-md p-2 mb-3 text-xs"
             style={{ background: 'rgba(16,185,129,0.10)', color: '#10b981' }}>{msg}</div>
      )}

      <div className="flex gap-4">
        {/* 平台列表 */}
        <div className="w-[180px] shrink-0 rounded-lg overflow-hidden self-start" style={card}>
          {rules.map(r => (
            <button key={r.platform} type="button"
                    onClick={() => setActive(r.platform)}
                    className="w-full text-left px-3 py-2.5 text-sm flex items-center justify-between"
                    style={{
                      background: active === r.platform ? 'var(--bg-tertiary)' : 'transparent',
                      color: r.rules_text ? 'var(--text-primary)' : 'var(--text-muted)',
                      borderBottom: '1px solid var(--border-color)',
                    }}>
              <span>{r.platform}</span>
              <span className="flex items-center gap-1">
                {r.pending_rules_text && (
                  <span className="text-[10px] px-1 rounded"
                        style={{ background: 'rgba(234,179,8,0.15)', color: '#eab308' }}
                        title="有待采纳的学习增量">增量</span>
                )}
                {r.rejected_count > 0 && (
                  <span className="text-[10px] text-muted tabular-nums"
                        title="已回填的平台拒稿数">{r.rejected_count}</span>
                )}
              </span>
            </button>
          ))}
        </div>

        {/* 编辑器 */}
        <div className="flex-1 min-w-0">
          {!current ? (
            <div className="rounded-lg p-8 text-center text-sm text-muted" style={card}>加载中…</div>
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg p-3" style={card}>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-sm font-medium text-primary">{current.platform} 审核红线</span>
                  <span className="text-[11px] text-muted">
                    {current.updated_at ? `更新于 ${current.updated_at.replace('T', ' ').slice(0, 16)}` : '尚未配置'}
                  </span>
                  <div className="flex-1" />
                  <button type="button" disabled={busy !== null} onClick={seed}
                          className="text-xs px-2.5 py-1 rounded-md disabled:opacity-40"
                          style={{ color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>
                    {busy === 'seed' ? '生成中…' : '✨ AI 生成初稿'}
                  </button>
                  <button type="button" disabled={busy !== null || !dirty} onClick={save}
                          className="text-xs px-3 py-1 rounded-md text-white disabled:opacity-40"
                          style={{ background: 'var(--accent-primary)' }}>
                    {busy === 'save' ? '…' : '保存'}
                  </button>
                </div>
                <textarea
                  className="w-full rounded-md p-2.5 text-xs leading-5 font-mono"
                  style={{ ...inputStyle, minHeight: 320, resize: 'vertical' }}
                  placeholder={'每条一行,以「- 」开头,例如:\n- 禁止绝对化用语(最/第一/唯一/100%)\n- 正文不得出现微信号 / 二维码 / 站外链接\n- 医疗、金融领域表述不得承诺效果或收益'}
                  value={draft}
                  onChange={e => { setDraft(e.target.value); setDirty(true); }}
                />
              </div>

              {current.pending_rules_text && (
                <div className="rounded-lg p-3"
                     style={{ background: 'rgba(234,179,8,0.06)', border: '1px solid rgba(234,179,8,0.35)' }}>
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-sm font-medium" style={{ color: '#eab308' }}>
                      待采纳的学习增量
                    </span>
                    <span className="text-[11px] text-muted">
                      从该平台已回填的拒稿原因提炼;采纳后并入上方规则生效
                    </span>
                    <div className="flex-1" />
                    <button type="button" disabled={busy !== null} onClick={dismissPending}
                            className="text-xs px-2.5 py-1 rounded-md disabled:opacity-40"
                            style={{ color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>
                      忽略
                    </button>
                    <button type="button" disabled={busy !== null} onClick={approve}
                            className="text-xs px-3 py-1 rounded-md text-white disabled:opacity-40"
                            style={{ background: '#eab308' }}>
                      {busy === 'approve' ? '…' : '✓ 采纳并生效'}
                    </button>
                  </div>
                  <pre className="text-xs leading-5 whitespace-pre-wrap text-primary m-0">
                    {current.pending_rules_text}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
