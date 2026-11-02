// 对外集成 Tab —— 自助生成「接入 token」,把本账号的 GEO agent 作为 skill 接进外部 agent(小龙虾)。
// 生成后直接给出一行安装命令(用当前站点 origin,自动对齐 test/prod),复制即用。
import { useCallback, useEffect, useState } from 'react';

const API_BASE = (import.meta.env.VITE_API_URL as string) || '/api';

interface TokenRow {
  tid: string;
  caps: string;
  label: string;
  enabled: boolean;
  expires_at: string | null;
  created_at: string | null;
}

const card: React.CSSProperties = { background: 'var(--bg-card)', border: '1px solid var(--border-color)' };

type PField = [key: string, label: string, placeholder: string];
interface IMPlatform { key: 'feishu' | 'wecom' | 'dingtalk'; name: string; idLabel: string; callbackWhere: string; note: string; fields: PField[] }
const IM_PLATFORMS: IMPlatform[] = [
  {
    key: 'feishu', name: '飞书', idLabel: 'App ID', callbackWhere: '事件订阅',
    note: '回飞书:订阅「接收消息 im.message.receive_v1」事件 + 开 im:message 权限 + 创建版本并发布,即可在飞书内对话。',
    fields: [
      ['app_id', 'App ID', 'cli_xxxxx'], ['app_secret', 'App Secret', '应用密钥'],
      ['verify_token', 'Verification Token', '事件订阅校验串'], ['aes_key', 'Encrypt Key(可选,留空=不加密)', '留空即可'],
    ],
  },
  {
    key: 'wecom', name: '企业微信', idLabel: 'CorpID', callbackWhere: '接收消息服务器配置',
    note: '回企微:在应用「接收消息」里填回调URL + Token + EncodingAESKey,可信域名/IP 配好,即可对话。',
    fields: [
      ['app_id', 'CorpID(企业ID)', 'ww_xxxxx'], ['app_secret', 'Secret(应用Secret)', ''],
      ['agentid', 'AgentId(应用ID)', '如 1000002'],
      ['verify_token', 'Token', '接收消息 Token'], ['aes_key', 'EncodingAESKey', '43 位'],
    ],
  },
  {
    key: 'dingtalk', name: '钉钉', idLabel: 'AppKey', callbackWhere: '机器人 · 消息接收地址',
    note: '回钉钉:在机器人配置里把「消息接收地址」填为上面的回调URL,发布机器人,@它即可对话。',
    fields: [
      ['app_id', 'AppKey(机器人 robotCode)', ''], ['app_secret', 'AppSecret', '用于验签'],
    ],
  },
];

function authHeaders(): HeadersInit {
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('token') || ''}` };
}

function CopyBtn({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={() => { void navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}
      className="px-3 py-1.5 rounded-md text-xs font-semibold transition-opacity"
      style={{ background: 'var(--accent-primary)', color: '#fff' }}
    >
      {done ? '已复制 ✓' : '复制'}
    </button>
  );
}

export function AgentIntegrationTab() {
  const [tokens, setTokens] = useState<TokenRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [label, setLabel] = useState('');
  const [fresh, setFresh] = useState<string | null>(null);   // 刚生成的明文 token(只显示这一次)
  const [err, setErr] = useState('');

  // IM 接入器(自建应用):支持飞书 / 企业微信 / 钉钉
  const [imPlatform, setImPlatform] = useState<'feishu' | 'wecom' | 'dingtalk'>('feishu');
  const [im, setIm] = useState<Record<string, string>>({});
  const [imConns, setImConns] = useState<Array<{ id: number; platform: string; app_id: string; app_secret_masked: string; enabled: boolean }>>([]);
  const [imBusy, setImBusy] = useState(false);
  const [imMsg, setImMsg] = useState('');
  const [bindCode, setBindCode] = useState('');

  // 快捷按钮/菜单配置编辑器(按连接器)
  const [cfgFor, setCfgFor] = useState<number | null>(null);
  const [qa, setQa] = useState<string[][]>([]);            // [[label, query], ...]
  const [mm, setMm] = useState<string[][]>([]);            // [[event_key, query], ...]
  const [cfgBusy, setCfgBusy] = useState(false);
  const [cfgMsg, setCfgMsg] = useState('');
  // 推送目标:webhook(可多个)+ bot 群,简报/告警群发
  const [pt, setPt] = useState<Array<{ type: string; name: string; url: string; secret: string; chat_id: string; enabled: boolean }>>([]);
  const [ptBusy, setPtBusy] = useState(false);
  const [ptMsg, setPtMsg] = useState('');

  const origin = window.location.origin;
  const installCmd = fresh ? `curl -fsSL ${origin}/skill/install.sh | bash -s -- ${fresh}` : '';
  const curPlatform = IM_PLATFORMS.find((p) => p.key === imPlatform)!;
  const imCallback = `${origin}/api/agent/im/${imPlatform}/callback`;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/account/agent-tokens`, { headers: authHeaders() });
      const d = await r.json();
      setTokens(d.tokens || []);
      const r2 = await fetch(`${API_BASE}/account/im-connectors`, { headers: authHeaders() });
      const d2 = await r2.json();
      setImConns(d2.connectors || []);
    } catch { setErr('加载失败'); } finally { setLoading(false); }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const openCfg = async (cid: number) => {
    if (cfgFor === cid) { setCfgFor(null); return; }
    setCfgFor(cid); setCfgMsg(''); setQa([]); setMm([]); setPt([]); setPtMsg('');
    try {
      const r = await fetch(`${API_BASE}/account/im-connector/${cid}/quick-config`, { headers: authHeaders() });
      const d = await r.json();
      setQa((d.quick_actions || []).map((x: string[]) => [x[0] || '', x[1] || '']));
      setMm(Object.entries(d.menu_map || {}).map(([k, v]) => [k, String(v)]));
    } catch { setCfgMsg('加载失败'); }
    try {
      const rp = await fetch(`${API_BASE}/account/im-connector/${cid}/push-targets`, { headers: authHeaders() });
      const dp = await rp.json();
      setPt((dp.push_targets || []).map((t: Record<string, unknown>) => ({
        type: String(t.type || 'webhook'), name: String(t.name || ''), url: String(t.url || ''),
        secret: String(t.secret || ''), chat_id: String(t.chat_id || ''), enabled: t.enabled !== false,
      })));
    } catch { /* 推送目标可选,加载失败不阻塞 */ }
  };
  const saveCfg = async (cid: number) => {
    setCfgBusy(true); setCfgMsg('');
    try {
      const menu_map: Record<string, string> = {};
      mm.forEach(([k, v]) => { if (k.trim() && v.trim()) menu_map[k.trim()] = v.trim(); });
      const quick_actions = qa.filter(([l, q]) => l.trim() && q.trim()).map(([l, q]) => [l.trim(), q.trim()]);
      const r = await fetch(`${API_BASE}/account/im-connector/${cid}/quick-config`, {
        method: 'POST', headers: authHeaders(), body: JSON.stringify({ quick_actions, menu_map }),
      });
      if (!r.ok) throw new Error(await r.text());
      setCfgMsg('✅ 已保存,下次回复/菜单点击即生效');
    } catch { setCfgMsg('保存失败'); } finally { setCfgBusy(false); }
  };
  const savePt = async (cid: number) => {
    setPtBusy(true); setPtMsg('');
    try {
      // webhook 全部保留(含空 URL 占位,后端会把空 URL 的强制不启用);bot 需有 chat_id
      const push_targets = pt.filter((t) => t.type === 'webhook' || (t.type === 'bot' && t.chat_id.trim()));
      const r = await fetch(`${API_BASE}/account/im-connector/${cid}/push-targets`, {
        method: 'POST', headers: authHeaders(), body: JSON.stringify({ push_targets }),
      });
      if (!r.ok) throw new Error(await r.text());
      setPtMsg('✅ 已保存,简报/告警将按此推送');
    } catch { setPtMsg('保存失败'); } finally { setPtBusy(false); }
  };

  const saveIm = async () => {
    setImBusy(true); setImMsg('');
    try {
      const r = await fetch(`${API_BASE}/account/im-connector`, {
        method: 'POST', headers: authHeaders(),
        body: JSON.stringify({ platform: imPlatform, ...im }),
      });
      if (!r.ok) throw new Error(await r.text());
      setImMsg('✅ 已保存。把上面的回调地址填回对应平台即可。');
      setIm({});
      await reload();
    } catch (e) { setImMsg(`保存失败:${e instanceof Error ? e.message : e}`); } finally { setImBusy(false); }
  };

  const deleteIm = async (id: number) => {
    if (!confirm('确认删除此 IM 接入?删除后机器人将无法再回复。')) return;
    await fetch(`${API_BASE}/account/im-connector/${id}/delete`, { method: 'POST', headers: authHeaders() });
    await reload();
  };

  const genBindCode = async () => {
    setBindCode('');
    try {
      const r = await fetch(`${API_BASE}/account/im-bind-code`, { method: 'POST', headers: authHeaders() });
      const d = await r.json();
      setBindCode(d.code || '');
    } catch { setBindCode('生成失败'); }
  };

  const generate = async () => {
    setBusy(true); setErr(''); setFresh(null);
    try {
      const r = await fetch(`${API_BASE}/account/agent-token`, {
        method: 'POST', headers: authHeaders(),
        body: JSON.stringify({ label }),
      });
      if (!r.ok) throw new Error(await r.text());
      const d = await r.json();
      setFresh(d.token);
      setLabel('');
      await reload();
    } catch (e) { setErr(`生成失败:${e instanceof Error ? e.message : e}`); } finally { setBusy(false); }
  };

  const revoke = async (tid: string) => {
    if (!confirm(`确认吊销 ${tid}?吊销后用此 token 的对接立即失效。`)) return;
    await fetch(`${API_BASE}/account/agent-token/${tid}/revoke`, { method: 'POST', headers: authHeaders() });
    await reload();
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-primary">对接集成</h1>
        <p className="text-sm text-secondary mt-1">
          把本账号的 GEO 优化助手接进你自己的 AI agent(小龙虾)。生成一个接入 token,复制一行命令即可安装。
        </p>
      </div>

      {/* 生成区 */}
      <div className="rounded-xl p-5" style={card}>
        <h2 className="text-base font-semibold text-primary mb-4">生成接入 token</h2>
        <div className="flex flex-wrap items-end gap-4">
          <label className="text-sm flex-1 min-w-[180px]">
            <span className="block text-secondary mb-1">备注(可选)</span>
            <input
              value={label} onChange={(e) => setLabel(e.target.value)} placeholder="如:给某某小龙虾"
              className="w-full px-3 py-2 rounded-lg text-sm"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
            />
          </label>
          <button
            onClick={() => void generate()} disabled={busy}
            className="px-5 py-2 rounded-lg text-sm font-semibold transition-opacity"
            style={{ background: 'var(--accent-primary)', color: '#fff', opacity: busy ? 0.5 : 1 }}
          >
            {busy ? '生成中…' : '生成'}
          </button>
        </div>
        <p className="text-xs text-secondary mt-3">token 含完整对接能力(查数据 / 诊断 / 产稿);真实对外发布不在对接能力内(由平台护栏控制)。token 等同密钥,只显示一次,请妥善保管。</p>
        {err && <p className="text-xs mt-2" style={{ color: '#f43f5e' }}>{err}</p>}
      </div>

      {/* 刚生成:token + 安装命令(只此一次)*/}
      {fresh && (
        <div className="rounded-xl p-5" style={{ ...card, borderColor: 'var(--accent-primary)' }}>
          <h2 className="text-base font-semibold text-primary mb-1">✅ 已生成(请立即复制,关闭后不再显示)</h2>
          <p className="text-xs text-secondary mb-3">在对方 agent 的机器上执行下面这行,自动安装 skill + 写入 token,装完即用:</p>
          <div className="flex items-center gap-2 mb-4">
            <code className="flex-1 px-3 py-2 rounded-lg text-xs break-all" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
              {installCmd}
            </code>
            <CopyBtn text={installCmd} />
          </div>
          <p className="text-xs text-secondary mb-1">token(单独用):</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 rounded-lg text-xs break-all" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
              {fresh}
            </code>
            <CopyBtn text={fresh} />
          </div>
        </div>
      )}

      {/* 已有 token 列表 */}
      <div className="rounded-xl p-5" style={card}>
        <h2 className="text-base font-semibold text-primary mb-4">已发放的 token</h2>
        {loading ? (
          <p className="text-sm text-secondary">加载中…</p>
        ) : tokens.length === 0 ? (
          <p className="text-sm text-secondary">还没有 token。上面生成一个开始对接。</p>
        ) : (
          <div className="space-y-2">
            {tokens.map((tk) => (
              <div key={tk.tid} className="flex items-center justify-between gap-3 py-2 px-3 rounded-lg" style={{ background: 'var(--bg-surface)' }}>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-primary truncate">
                    {tk.label || tk.tid} <span className="text-xs text-secondary">({tk.caps})</span>
                  </div>
                  <div className="text-xs text-secondary">
                    {tk.enabled ? '启用' : '已吊销'} · 到期 {tk.expires_at?.slice(0, 10) || '—'} · {tk.tid}
                  </div>
                </div>
                {tk.enabled && (
                  <button
                    onClick={() => void revoke(tk.tid)}
                    className="px-3 py-1.5 rounded-md text-xs font-semibold whitespace-nowrap"
                    style={{ color: '#f43f5e', border: '1px solid rgba(244,63,94,0.35)', background: 'transparent' }}
                  >
                    吊销
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── IM 对话接入(自建应用):飞书 / 企业微信 / 钉钉 ── */}
      <div className="rounded-xl p-5" style={card}>
        <h2 className="text-base font-semibold text-primary mb-1">IM 对话接入</h2>
        <p className="text-sm text-secondary mb-4">
          让团队在 IM 里直接 @机器人 问「我被搜到几个?」「帮我诊断」——非技术同事零安装、零命令。
          在你公司的 IM 后台建一个<strong>企业自建应用/机器人</strong>,把凭证填到这里(应用与凭证都在你自己的 IM,不经过我们)。
        </p>

        {/* 平台切换 */}
        <div className="flex gap-2 mb-4">
          {IM_PLATFORMS.map((p) => (
            <button key={p.key} onClick={() => { setImPlatform(p.key); setIm({}); setImMsg(''); }}
              className="px-4 py-1.5 rounded-lg text-sm font-medium"
              style={imPlatform === p.key
                ? { background: 'var(--accent-primary)', color: '#fff' }
                : { background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>
              {p.name}
            </button>
          ))}
        </div>

        {/* 现有连接(当前平台) */}
        {imConns.filter((c) => c.platform === imPlatform).map((c) => (
          <div key={c.id} className="mb-3">
            <div className="flex items-center justify-between gap-3 py-2 px-3 rounded-lg" style={{ background: 'var(--bg-surface)' }}>
              <div className="text-sm text-primary min-w-0">
                已连接 · {curPlatform.idLabel} <span className="text-secondary">{c.app_id}</span> · 密钥 {c.app_secret_masked}
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => void openCfg(c.id)} className="px-3 py-1.5 rounded-md text-xs font-semibold whitespace-nowrap" style={{ color: 'var(--accent-primary)', border: '1px solid var(--border-color)', background: 'transparent' }}>
                  {cfgFor === c.id ? '收起' : '配置(推送目标/按钮)'}
                </button>
                <button onClick={() => void deleteIm(c.id)} className="px-3 py-1.5 rounded-md text-xs font-semibold whitespace-nowrap" style={{ color: '#f43f5e', border: '1px solid rgba(244,63,94,0.35)', background: 'transparent' }}>删除</button>
              </div>
            </div>

            {cfgFor === c.id && (
              <div className="mt-2 p-4 rounded-lg" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
                {/* 回复底部快捷按钮 */}
                <div className="text-sm font-semibold text-primary mb-1">回复底部快捷按钮(最多 6 个)</div>
                <p className="text-xs text-secondary mb-2">每条回复底部展示这些按钮,点击即把对应问句发给 AI 营销官。</p>
                {qa.map((row, i) => (
                  <div key={i} className="flex items-center gap-2 mb-2">
                    <input value={row[0]} onChange={(e) => setQa(qa.map((r, j) => j === i ? [e.target.value, r[1]] : r))} placeholder="按钮文字 如 📰 今日舆情" className="flex-1 px-2 py-1.5 rounded-md text-sm" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
                    <input value={row[1]} onChange={(e) => setQa(qa.map((r, j) => j === i ? [r[0], e.target.value] : r))} placeholder="点击发送的问句" className="flex-[2] px-2 py-1.5 rounded-md text-sm" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
                    <button onClick={() => setQa(qa.filter((_, j) => j !== i))} className="px-2 py-1 rounded-md text-xs" style={{ color: '#f43f5e' }}>移除</button>
                  </div>
                ))}
                {qa.length < 6 && (
                  <button onClick={() => setQa([...qa, ['', '']])} className="text-xs font-semibold mb-3" style={{ color: 'var(--accent-primary)' }}>+ 添加按钮</button>
                )}

                {/* 飞书菜单映射(仅飞书) */}
                {imPlatform === 'feishu' && (
                  <>
                    <div className="text-sm font-semibold text-primary mt-3 mb-1">飞书底部菜单映射(event_key → 问句)</div>
                    <p className="text-xs text-secondary mb-2">在飞书后台配机器人菜单时,每个菜单项设一个 event_key,这里把 key 映射成问句(也可直接把菜单 key 填成问句、此处不配)。</p>
                    {mm.map((row, i) => (
                      <div key={i} className="flex items-center gap-2 mb-2">
                        <input value={row[0]} onChange={(e) => setMm(mm.map((r, j) => j === i ? [e.target.value, r[1]] : r))} placeholder="event_key 如 today" className="flex-1 px-2 py-1.5 rounded-md text-sm" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
                        <input value={row[1]} onChange={(e) => setMm(mm.map((r, j) => j === i ? [r[0], e.target.value] : r))} placeholder="对应问句(填 __help__ 弹功能清单)" className="flex-[2] px-2 py-1.5 rounded-md text-sm" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
                        <button onClick={() => setMm(mm.filter((_, j) => j !== i))} className="px-2 py-1 rounded-md text-xs" style={{ color: '#f43f5e' }}>移除</button>
                      </div>
                    ))}
                    <button onClick={() => setMm([...mm, ['', '']])} className="text-xs font-semibold mb-3" style={{ color: 'var(--accent-primary)' }}>+ 添加菜单项</button>
                  </>
                )}

                <div className="mt-3 flex items-center gap-3">
                  <button onClick={() => void saveCfg(c.id)} disabled={cfgBusy} className="px-4 py-1.5 rounded-lg text-sm font-semibold" style={{ background: 'var(--accent-primary)', color: '#fff', opacity: cfgBusy ? 0.5 : 1 }}>{cfgBusy ? '保存中…' : '保存配置'}</button>
                  {cfgMsg && <span className="text-xs" style={{ color: cfgMsg.startsWith('✅') ? 'var(--accent-secondary)' : '#f43f5e' }}>{cfgMsg}</span>}
                </div>

                {/* 推送目标:webhook(可多个)+ bot 群,简报/告警群发 */}
                <div className="text-sm font-semibold text-primary mt-5 mb-1">推送目标(简报/告警群发)</div>
                <p className="text-xs text-secondary mb-2">支持多个飞书自定义机器人 webhook + 应用机器人群,每个可单独开关。webhook:飞书群「设置 → 群机器人 → 添加自定义机器人」复制 URL(有加签则填密钥);群机器人:填群 chat_id(oc_…)。</p>
                {pt.map((t, i) => (
                  <div key={i} className="flex items-center gap-2 mb-2 flex-wrap">
                    <select value={t.type} onChange={(e) => setPt(pt.map((r, j) => j === i ? { ...r, type: e.target.value } : r))} className="px-2 py-1.5 rounded-md text-sm" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
                      <option value="webhook">webhook</option>
                      <option value="bot">群机器人</option>
                    </select>
                    <input value={t.name} onChange={(e) => setPt(pt.map((r, j) => j === i ? { ...r, name: e.target.value } : r))} placeholder="名称 如 测试群" className="px-2 py-1.5 rounded-md text-sm w-28" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
                    {t.type === 'webhook' ? (
                      <>
                        <input value={t.url} onChange={(e) => setPt(pt.map((r, j) => j === i ? { ...r, url: e.target.value } : r))} placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/…" className="flex-1 px-2 py-1.5 rounded-md text-sm" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', minWidth: '200px' }} />
                        <input value={t.secret} onChange={(e) => setPt(pt.map((r, j) => j === i ? { ...r, secret: e.target.value } : r))} placeholder="加签密钥(可选)" className="px-2 py-1.5 rounded-md text-sm w-32" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
                      </>
                    ) : (
                      <input value={t.chat_id} onChange={(e) => setPt(pt.map((r, j) => j === i ? { ...r, chat_id: e.target.value } : r))} placeholder="群 chat_id (oc_…)" className="flex-1 px-2 py-1.5 rounded-md text-sm" style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)', color: 'var(--text-primary)', minWidth: '200px' }} />
                    )}
                    <label className="flex items-center gap-1 text-xs text-secondary"><input type="checkbox" checked={t.enabled} onChange={(e) => setPt(pt.map((r, j) => j === i ? { ...r, enabled: e.target.checked } : r))} />启用</label>
                    <button onClick={() => setPt(pt.filter((_, j) => j !== i))} className="px-2 py-1 rounded-md text-xs" style={{ color: '#f43f5e' }}>移除</button>
                  </div>
                ))}
                <div className="flex items-center gap-3 mt-1">
                  <button onClick={() => setPt([...pt, { type: 'webhook', name: '', url: '', secret: '', chat_id: '', enabled: true }])} className="text-xs font-semibold" style={{ color: 'var(--accent-primary)' }}>+ webhook</button>
                  <button onClick={() => setPt([...pt, { type: 'bot', name: '', url: '', secret: '', chat_id: '', enabled: true }])} className="text-xs font-semibold" style={{ color: 'var(--accent-primary)' }}>+ 群机器人</button>
                  <button onClick={() => void savePt(c.id)} disabled={ptBusy} className="px-4 py-1.5 rounded-lg text-sm font-semibold" style={{ background: 'var(--accent-secondary)', color: '#fff', opacity: ptBusy ? 0.5 : 1 }}>{ptBusy ? '保存中…' : '保存推送目标'}</button>
                  {ptMsg && <span className="text-xs" style={{ color: ptMsg.startsWith('✅') ? 'var(--accent-secondary)' : '#f43f5e' }}>{ptMsg}</span>}
                </div>
              </div>
            )}
          </div>
        ))}

        {/* 回调地址 */}
        <div className="mb-4">
          <p className="text-xs text-secondary mb-1">① 在{curPlatform.name}「{curPlatform.callbackWhere}」把回调/请求地址填成:</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 rounded-lg text-xs break-all" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>{imCallback}</code>
            <CopyBtn text={imCallback} />
          </div>
        </div>

        {/* 凭证表单(按平台) */}
        <p className="text-xs text-secondary mb-2">② 把{curPlatform.name}应用里的凭证填进来:</p>
        <div className="grid sm:grid-cols-2 gap-3">
          {curPlatform.fields.map(([k, lbl, ph]) => (
            <label key={k} className="text-sm">
              <span className="block text-secondary mb-1">{lbl}</span>
              <input
                value={im[k] || ''}
                onChange={(e) => setIm((p) => ({ ...p, [k]: e.target.value }))}
                placeholder={ph}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
              />
            </label>
          ))}
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={() => void saveIm()} disabled={imBusy || !im.app_id || !im.app_secret}
            className="px-5 py-2 rounded-lg text-sm font-semibold"
            style={{ background: 'var(--accent-primary)', color: '#fff', opacity: imBusy || !im.app_id || !im.app_secret ? 0.5 : 1 }}
          >
            {imBusy ? '保存中…' : '保存并连接'}
          </button>
          {imMsg && <span className="text-xs" style={{ color: imMsg.startsWith('✅') ? 'var(--accent-secondary)' : '#f43f5e' }}>{imMsg}</span>}
        </div>
        <p className="text-xs text-secondary mt-3">③ {curPlatform.note}</p>
      </div>

      {/* ── 飞书绑定码(应用市场版机器人,每个使用者各自绑定)── */}
      <div className="rounded-xl p-5" style={card}>
        <h2 className="text-base font-semibold text-primary mb-1">飞书绑定码(应用市场机器人)</h2>
        <p className="text-sm text-secondary mb-4">
          如果你用的是 Vigilath 上架在飞书应用市场的机器人(无需自建应用),首次在飞书里跟它对话前,
          先在这里生成绑定码,然后**把绑定码发给机器人**,即可把飞书账号绑定到当前 Vigilath 账号。
        </p>
        <div className="flex items-center gap-3">
          <button
            onClick={() => void genBindCode()}
            className="px-5 py-2 rounded-lg text-sm font-semibold"
            style={{ background: 'var(--accent-primary)', color: '#fff' }}
          >
            生成绑定码
          </button>
          {bindCode && (
            <>
              <code className="px-4 py-2 rounded-lg text-lg font-bold tracking-widest" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--accent-secondary)' }}>
                {bindCode}
              </code>
              <CopyBtn text={bindCode} />
              <span className="text-xs text-secondary">10 分钟内有效,发给飞书机器人即可绑定</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
