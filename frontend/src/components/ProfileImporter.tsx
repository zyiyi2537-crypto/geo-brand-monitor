// 资料上传 — 两类资料分两个 sub-tab.
//
// ① 文本资料(.txt / .md / .docx / .pdf / 文本粘贴):走 LLM 抽取,自动回填 BrandProfile.
//    后端:POST /api/ai-telemetry/profile/extract(JSON)/ /profile/extract-file(multipart)
//    没配 DEEPSEEK_API_KEY 时后端 503,前端弹错误而不是静默吞.
//
// ② 图片 / 视频:落服务器(data/topic_media/{topic_id}/),作为后续生稿 / 发文的素材库.
//    后端:POST /topics/{id}/media,GET /topics/{id}/media,DELETE /topics/{id}/media/{mid}.
//    需要 topicId — 新建 topic 时还没有 ID,这一栏会显示「先保存主题以启用素材上传」.
//
// 合并策略(仅文本):
//   - 「填充空白」:只填当前资料里为空的字段
//   - 「全部覆盖」:LLM 抽到的非空值都覆盖现有值
//   默认是「填充空白」,避免覆盖用户已经手填的内容.

import { useEffect, useRef, useState } from 'react';
import type { BrandProfile } from '../services/aiTelemetryApi';
import { topicProfileApi, type TopicMedia } from '../services/topicProfileApi';

// 文本类 — 客户端 file.text() 读得到的就直接走 JSON 路径,docx / pdf 走 multipart 后端解析.
// .doc 旧二进制和扫描版 PDF 抽不到字会在后端 415,前端再翻译成友好提示.
const TEXT_EXTS = ['.txt', '.md'];
const BINARY_EXTS = ['.docx', '.pdf'];
const ACCEPT_TEXT_EXTS = [...TEXT_EXTS, ...BINARY_EXTS];
const MAX_TEXT_LEN = 60000;
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

// 媒体类 — 跟后端 ALLOWED_MEDIA_EXTS 对齐
const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'];
const VIDEO_EXTS = ['.mp4', '.mov', '.webm', '.m4v', '.mkv'];
const ACCEPT_MEDIA_EXTS = [...IMAGE_EXTS, ...VIDEO_EXTS];
const MAX_MEDIA_BYTES = 50 * 1024 * 1024;

type SubTab = 'text' | 'media';

interface ProfileImporterProps {
  profile: BrandProfile;
  onApply: (next: BrandProfile) => void;
  token: string;
  disabled?: boolean;
  // 可选:把 LLM 顺手给的种子提示词候选合并到种子词步骤。
  onApplySeeds?: (suggestions: string[]) => void;
  // 可选:topic ID — 已存在的主题直接走服务器上传。
  topicId?: number;
  // 可选:本地暂存的待上传文件(没 topicId 时用)。父组件持有,
  // 这样切 step / 关闭 modal 不丢;TopicEditor 在 persistTopic 拿到 saved.id 后批量 flush。
  pendingMediaFiles?: File[];
  onPendingMediaFilesChange?: (files: File[]) => void;
}

export function ProfileImporter({
  profile, onApply, token, disabled, onApplySeeds,
  topicId, pendingMediaFiles, onPendingMediaFilesChange,
}: ProfileImporterProps) {
  const [tab, setTab] = useState<SubTab>('text');
  const [open, setOpen] = useState(true);

  return (
    <section className="rounded-md p-4"
             style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <header className="flex items-center justify-between gap-3 mb-2">
        <div>
          <h3 className="text-sm font-semibold text-primary">资料上传</h3>
          <p className="text-xs text-muted mt-0.5">
            文本资料 AI 解析后自动回填表单;图片 / 视频 落服务器作为后续发文素材库。
          </p>
        </div>
        <button type="button" onClick={() => setOpen(o => !o)}
                disabled={disabled}
                className="text-xs px-2.5 py-1 rounded-md"
                style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                         opacity: disabled ? 0.5 : 1 }}>
          {open ? '收起' : '展开'}
        </button>
      </header>

      {open && (
        <>
          <div className="flex gap-1 border-b mb-3" style={{ borderColor: 'var(--border-color)' }}>
            <SubTabBtn active={tab === 'text'} onClick={() => setTab('text')}>文本资料(自动回填)</SubTabBtn>
            <SubTabBtn active={tab === 'media'} onClick={() => setTab('media')}>图片 / 视频(发文素材)</SubTabBtn>
          </div>

          {tab === 'text' && (
            <TextSection profile={profile} onApply={onApply} token={token}
                         disabled={disabled} onApplySeeds={onApplySeeds} />
          )}
          {tab === 'media' && (
            <MediaSection topicId={topicId} token={token} disabled={disabled}
                          pendingFiles={pendingMediaFiles}
                          onPendingFilesChange={onPendingMediaFilesChange} />
          )}
        </>
      )}
    </section>
  );
}

function SubTabBtn({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick}
            className="px-3 py-1.5 text-xs -mb-px"
            style={{
              borderBottom: active ? '2px solid var(--accent-primary)' : '2px solid transparent',
              color: active ? 'var(--accent-primary)' : 'var(--text-secondary)',
            }}>
      {children}
    </button>
  );
}


// ─────────────── 子页 ① 文本资料 ────────────────────────────

interface TextSectionProps {
  profile: BrandProfile;
  onApply: (next: BrandProfile) => void;
  token: string;
  disabled?: boolean;
  onApplySeeds?: (suggestions: string[]) => void;
}

function TextSection({ profile, onApply, token, disabled, onApplySeeds }: TextSectionProps) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // 拖入后立刻 setText + 异步 callExtract,closure 抓的 profile 是回调时的 props,
  // 父组件 re-render 后 profile 新值靠 ref 取。
  const profileRef = useRef(profile);
  profileRef.current = profile;

  const callExtract = async (rawText: string, mode: 'fill-blank' | 'overwrite') => {
    const t = rawText.trim();
    if (!t || t.length < 10) {
      setErr('请先拖入文件或在文本框里粘贴内容(至少 10 个字符)');
      return;
    }
    setBusy(true); setErr(null); setOkMsg(null);
    try {
      const resp = await topicProfileApi.extractProfile(t, token);
      const merged = mergeProfile(profileRef.current, resp.profile, mode);
      const changed = countChanged(profileRef.current, merged);
      onApply(merged);
      const seeds = resp.seed_suggestions || [];
      if (seeds.length > 0 && onApplySeeds) onApplySeeds(seeds);
      const seedHint = seeds.length > 0 && onApplySeeds ? `,种子提示词候选 ${seeds.length} 条已带到下一步` : '';
      if (changed === 0) {
        setOkMsg(`没解出可用字段(原文可能太短或没有品牌信息)${seedHint},可手动调整后再试`);
      } else {
        setOkMsg(`已${mode === 'overwrite' ? '覆盖' : '填充'} ${changed} 个字段${seedHint}`);
      }
    } catch (e) {
      setErr(humanizeFetchError(e));
    } finally {
      setBusy(false);
    }
  };

  const callExtractFile = async (file: File, mode: 'fill-blank' | 'overwrite') => {
    setBusy(true); setErr(null);
    try {
      const resp = await topicProfileApi.extractProfileFile(file, token);
      const merged = mergeProfile(profileRef.current, resp.profile, mode);
      const changed = countChanged(profileRef.current, merged);
      onApply(merged);
      const seeds = resp.seed_suggestions || [];
      if (seeds.length > 0 && onApplySeeds) onApplySeeds(seeds);
      const seedHint = seeds.length > 0 && onApplySeeds ? `,种子提示词候选 ${seeds.length} 条已带到下一步` : '';
      if (changed === 0) {
        setOkMsg(`没解出可用字段(文件可能太短或没有品牌信息)${seedHint},可手动调整后再试`);
      } else {
        setOkMsg(`已${mode === 'overwrite' ? '覆盖' : '填充'} ${changed} 个字段${seedHint}`);
      }
    } catch (e) {
      setErr(humanizeFetchError(e));
    } finally {
      setBusy(false);
    }
  };

  const readFile = async (file: File) => {
    const ext = (file.name.match(/\.[a-z0-9]+$/i)?.[0] || '').toLowerCase();
    const isText = TEXT_EXTS.includes(ext);
    const isBinary = BINARY_EXTS.includes(ext);
    if (!isText && !isBinary) {
      if (ext === '.doc') {
        setErr('暂不支持 .doc 旧格式,请用 Word「另存为」.docx 后重试');
      } else {
        setErr(`不支持的文件类型(${ext || '未知'});只接受 ${ACCEPT_TEXT_EXTS.join(' / ')}`);
      }
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      setErr(`文件过大(${Math.floor(file.size / 1024)} KB > ${MAX_UPLOAD_BYTES / 1024 / 1024} MB 上限),请精简后再试`);
      return;
    }

    if (isBinary) {
      setText('');
      setErr(null);
      setOkMsg(`已上传 ${file.name}(${Math.floor(file.size / 1024)} KB),后端正在解析…`);
      await callExtractFile(file, 'fill-blank');
      return;
    }

    try {
      const content = await file.text();
      const trimmed = content.length > MAX_TEXT_LEN ? content.slice(0, MAX_TEXT_LEN) : content;
      setText(trimmed);
      setErr(null);
      setOkMsg(`已读取 ${file.name}(${trimmed.length.toLocaleString()} 字),正在用 AI 解析…`);
      await callExtract(trimmed, 'fill-blank');
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    if (disabled || busy) return;
    const f = e.dataTransfer.files?.[0];
    if (f) readFile(f);
  };

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) readFile(f);
    e.target.value = '';
  };

  return (
    <div className="space-y-3">
      <div onDragOver={e => { e.preventDefault(); if (!disabled && !busy) setDrag(true); }}
           onDragLeave={() => setDrag(false)}
           onDrop={onDrop}
           onClick={() => fileInputRef.current?.click()}
           className="rounded-md p-4 text-center text-xs cursor-pointer transition-colors"
           style={{
             border: `1px dashed ${drag ? 'var(--accent-primary)' : 'var(--border-color)'}`,
             background: drag ? 'rgba(99,102,241,0.06)' : 'var(--bg-input)',
             color: 'var(--text-secondary)',
             opacity: disabled ? 0.5 : 1,
           }}>
        {drag ? '松开以读取' : (
          <>
            拖入文件或<span style={{ color: 'var(--accent-primary)' }}>点击选择</span>
            <span className="block text-muted mt-1">
              支持 .txt / .md / .docx / .pdf;.doc 旧格式请先另存为 .docx
            </span>
          </>
        )}
        <input ref={fileInputRef} type="file" accept={ACCEPT_TEXT_EXTS.join(',')}
               className="hidden" onChange={onPickFile} disabled={disabled || busy} />
      </div>

      <textarea value={text} onChange={e => setText(e.target.value.slice(0, MAX_TEXT_LEN))}
                rows={6}
                placeholder="或直接粘贴公司简介 / 官网文案 / PRD,AI 会从中抽取 6 大模块字段..."
                disabled={disabled || busy}
                className="w-full text-sm px-3 py-2 rounded-md"
                style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                         border: '1px solid var(--border-color)' }} />
      <div className="flex items-center justify-between gap-2 flex-wrap text-xs">
        <span className="text-muted">{text.length.toLocaleString()} / {MAX_TEXT_LEN.toLocaleString()} 字</span>
        <div className="flex items-center gap-2">
          <button type="button" disabled={disabled || busy || text.trim().length < 10}
                  onClick={() => callExtract(text, 'fill-blank')}
                  className="text-xs px-3 py-1.5 rounded-md text-white"
                  style={{ background: 'var(--accent-primary)',
                           opacity: (disabled || busy || text.trim().length < 10) ? 0.5 : 1 }}>
            {busy ? '解析中…' : 'AI 解析'}
          </button>
          <button type="button" disabled={disabled || busy || text.trim().length < 10}
                  onClick={() => callExtract(text, 'overwrite')}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)',
                           opacity: (disabled || busy || text.trim().length < 10) ? 0.5 : 1 }}>
            全部覆盖
          </button>
        </div>
      </div>
      {err && <div className="text-xs" style={{ color: '#ef4444' }}>{err}</div>}
      {okMsg && <div className="text-xs" style={{ color: '#10b981' }}>{okMsg}</div>}
    </div>
  );
}


// ─────────────── 子页 ② 图片 / 视频 ────────────────────────
//
// 两条上传路径:
//   1) topicId 已就绪(编辑场景 / TopicProfile)→ 直接 POST 到服务器
//   2) topicId 还没有(新建场景,用户还没保存主题)→ File 留在 parent 暂存,
//      显示本地预览;parent 在保存主题拿到 saved.id 后再批量 flush。
//
// pendingFiles / onPendingFilesChange 是 controlled — 由 parent (TopicEditor) 持有,
// 不放 MediaSection 内部 state,因为 step 1 ↔ step 2 切换会让本 section unmount。

interface MediaSectionProps {
  topicId?: number;
  token: string;
  disabled?: boolean;
  pendingFiles?: File[];
  onPendingFilesChange?: (files: File[]) => void;
}

function MediaSection({ topicId, token, disabled, pendingFiles, onPendingFilesChange }: MediaSectionProps) {
  const [list, setList] = useState<TopicMedia[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const stagingEnabled = typeof onPendingFilesChange === 'function';
  const pending = pendingFiles || [];

  const refresh = async () => {
    if (!topicId) return;
    setLoading(true); setErr(null);
    try {
      const items = await topicProfileApi.listMedia(topicId, token);
      setList(items);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (topicId) refresh();   }, [topicId]);

  // 校验 — 跟后端 ALLOWED_MEDIA_EXTS 对齐,文本错误友好化.
  const validate = (file: File): string | null => {
    const ext = (file.name.match(/\.[a-z0-9]+$/i)?.[0] || '').toLowerCase();
    if (!ACCEPT_MEDIA_EXTS.includes(ext)) {
      return `不支持的格式 ${ext || '未知'};只接受 ${ACCEPT_MEDIA_EXTS.join(' / ')}`;
    }
    if (file.size > MAX_MEDIA_BYTES) {
      return `文件过大(${Math.floor(file.size / 1024 / 1024)} MB > ${MAX_MEDIA_BYTES / 1024 / 1024} MB 上限)`;
    }
    return null;
  };

  const uploadOne = async (file: File) => {
    if (!topicId) return;
    const v = validate(file);
    if (v) { setErr(v); return; }
    setBusy(true); setErr(null);
    try {
      const m = await topicProfileApi.uploadMedia(topicId, file, token);
      setList(prev => [m, ...prev]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const stageOne = (file: File) => {
    if (!stagingEnabled) return;
    const v = validate(file);
    if (v) { setErr(v); return; }
    setErr(null);
    onPendingFilesChange!([...pending, file]);
  };

  const remove = async (mediaId: number) => {
    if (!topicId || busy) return;
    setBusy(true); setErr(null);
    try {
      await topicProfileApi.deleteMedia(topicId, mediaId, token);
      setList(prev => prev.filter(m => m.id !== mediaId));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const removePending = (idx: number) => {
    if (!stagingEnabled) return;
    onPendingFilesChange!(pending.filter((_, i) => i !== idx));
  };

  const handleFiles = (files: File[]) => {
    if (disabled || busy) return;
    for (const f of files) {
      if (topicId) void uploadOne(f);
      else if (stagingEnabled) stageOne(f);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault(); setDrag(false);
    handleFiles(Array.from(e.dataTransfer.files || []));
  };

  const onPickFiles = (e: React.ChangeEvent<HTMLInputElement>) => {
    handleFiles(Array.from(e.target.files || []));
    e.target.value = '';
  };

  // 既没 topicId、parent 也不提供暂存接口 → 给一个降级提示(目前没有调用方走到这里,留个保险)
  if (!topicId && !stagingEnabled) {
    return (
      <div className="rounded-md p-4 text-xs text-secondary"
           style={{ background: 'var(--bg-input)', border: '1px dashed var(--border-color)' }}>
        请先保存主题后再上传图片 / 视频。
      </div>
    );
  }

  const totalEmpty = !loading && list.length === 0 && pending.length === 0;

  return (
    <div className="space-y-3">
      <div onDragOver={e => { e.preventDefault(); if (!disabled && !busy) setDrag(true); }}
           onDragLeave={() => setDrag(false)}
           onDrop={onDrop}
           onClick={() => fileInputRef.current?.click()}
           className="rounded-md p-4 text-center text-xs cursor-pointer transition-colors"
           style={{
             border: `1px dashed ${drag ? 'var(--accent-primary)' : 'var(--border-color)'}`,
             background: drag ? 'rgba(99,102,241,0.06)' : 'var(--bg-input)',
             color: 'var(--text-secondary)',
             opacity: (disabled || busy) ? 0.5 : 1,
           }}>
        {drag ? '松开以上传' : (
          <>
            拖入图片 / 视频或<span style={{ color: 'var(--accent-primary)' }}>点击选择</span>
            <span className="block text-muted mt-1">
              支持 {IMAGE_EXTS.join(' / ')} / {VIDEO_EXTS.join(' / ')};单文件最大 {MAX_MEDIA_BYTES / 1024 / 1024} MB
            </span>
            {!topicId && stagingEnabled && (
              <span className="block mt-1" style={{ color: 'var(--accent-primary)' }}>
                主题尚未保存 — 文件先暂存浏览器,保存主题后会自动批量上传
              </span>
            )}
          </>
        )}
        <input ref={fileInputRef} type="file" multiple
               accept={ACCEPT_MEDIA_EXTS.join(',')}
               className="hidden" onChange={onPickFiles} disabled={disabled || busy} />
      </div>

      {err && <div className="text-xs" style={{ color: '#ef4444' }}>{err}</div>}
      {busy && <div className="text-xs text-muted">上传中…</div>}
      {loading && <div className="text-xs text-muted">加载中…</div>}
      {totalEmpty && (
        <div className="text-xs text-muted py-4 text-center">尚未上传任何素材</div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-2">
        {pending.map((f, i) => (
          <PendingCard key={`pending-${i}-${f.name}`} file={f}
                       onRemove={() => removePending(i)} disabled={disabled} />
        ))}
        {list.map(m => (
          <MediaCard key={m.id} media={m} token={token}
                     onRemove={() => remove(m.id)}
                     disabled={disabled || busy} />
        ))}
      </div>
    </div>
  );
}

function PendingCard({ file, onRemove, disabled }: {
  file: File; onRemove: () => void; disabled?: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const isImage = IMAGE_EXTS.includes((file.name.match(/\.[a-z0-9]+$/i)?.[0] || '').toLowerCase());
  useEffect(() => {
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  return (
    <div className="relative rounded-md overflow-hidden group"
         style={{ background: 'var(--bg-input)', border: '1px dashed var(--accent-primary)' }}>
      <div className="aspect-square flex items-center justify-center text-xs text-muted">
        {!url && <span>…</span>}
        {url && isImage && <img src={url} alt={file.name} className="w-full h-full object-cover" />}
        {url && !isImage && <video src={url} controls className="w-full h-full object-cover" />}
      </div>
      <div className="px-2 py-1 text-[10px] truncate"
           style={{ color: 'var(--accent-primary)' }}
           title={file.name}>
        暂存 · {file.name}
      </div>
      <button type="button" onClick={onRemove} disabled={disabled}
              className="absolute top-1 right-1 px-1.5 py-0.5 rounded-md text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
              style={{ background: 'rgba(239,68,68,0.85)', color: '#fff' }}>
        移除
      </button>
    </div>
  );
}

function MediaCard({ media, token, onRemove, disabled }: {
  media: TopicMedia; token: string; onRemove: () => void; disabled?: boolean;
}) {
  // 后端 blob 路由要 Bearer,直接 <img src> 拿不到 — 用 fetch + objectURL.
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let createdUrl: string | null = null;
    (async () => {
      try {
        const resp = await fetch(media.url, { headers: { Authorization: `Bearer ${token}` } });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const blob = await resp.blob();
        if (cancelled) return;
        createdUrl = URL.createObjectURL(blob);
        setBlobUrl(createdUrl);
      } catch (e) {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      if (createdUrl) URL.revokeObjectURL(createdUrl);
    };
  }, [media.url, token]);

  return (
    <div className="relative rounded-md overflow-hidden group"
         style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)' }}>
      <div className="aspect-square flex items-center justify-center text-xs text-muted">
        {err && <span style={{ color: '#ef4444' }}>{err}</span>}
        {!err && !blobUrl && <span>…</span>}
        {!err && blobUrl && media.kind === 'image' && (
          <img src={blobUrl} alt={media.filename}
               className="w-full h-full object-cover" />
        )}
        {!err && blobUrl && media.kind === 'video' && (
          <video src={blobUrl} controls className="w-full h-full object-cover" />
        )}
      </div>
      <div className="px-2 py-1 text-[10px] text-secondary truncate"
           title={media.filename}>
        {media.filename}
      </div>
      <button type="button" onClick={onRemove} disabled={disabled}
              className="absolute top-1 right-1 px-1.5 py-0.5 rounded-md text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
              style={{ background: 'rgba(239,68,68,0.85)', color: '#fff' }}>
        删除
      </button>
    </div>
  );
}


// ─────────────── merge 策略 ────────────────────────────────

function isBlank(v: unknown): boolean {
  if (v == null) return true;
  if (typeof v === 'string') return v.trim().length === 0;
  if (Array.isArray(v)) return v.length === 0;
  return false;
}

// 把 fetch 抛的 TypeError("Failed to fetch") 翻译成对用户更友好的提示.
// 常见诱因:中间代理(BMS02 EIP 映射)在 60s 把长连接砍掉,导致连接重置.
function humanizeFetchError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  if (/failed to fetch|networkerror|load failed/i.test(raw)) {
    return 'AI 解析连接被中断 — 多半是中间代理在 60s 把长请求砍掉了。请把原文缩短到 1000 字以内,或分两段粘贴再重试。';
  }
  return raw;
}

function mergeProfile(
  base: BrandProfile, extracted: BrandProfile, mode: 'fill-blank' | 'overwrite',
): BrandProfile {
  const out: Record<string, unknown> = { ...base };
  for (const key of Object.keys(extracted) as (keyof BrandProfile)[]) {
    const newVal = extracted[key];
    if (isBlank(newVal)) continue;
    if (mode === 'overwrite' || isBlank(base[key])) {
      out[key] = newVal;
    }
  }
  return out as unknown as BrandProfile;
}

function countChanged(a: BrandProfile, b: BrandProfile): number {
  let n = 0;
  for (const key of Object.keys(a) as (keyof BrandProfile)[]) {
    const av = a[key], bv = b[key];
    if (Array.isArray(av) && Array.isArray(bv)) {
      if (av.length !== bv.length || av.some((x, i) => x !== bv[i])) n++;
    } else if (av !== bv) {
      n++;
    }
  }
  return n;
}
