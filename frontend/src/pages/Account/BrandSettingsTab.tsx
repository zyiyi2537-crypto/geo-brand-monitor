// 品牌与监控配置 Tab — 统一放在账户中心.
//
// 4 个区块:
//   1. 品牌信息: 品牌名、股票代码、别名
//   2. 监控配置: 监测重点、关键词分组、排除词
//   3. 通知设置: 通知邮箱
//   4. 知识库:   品牌语调、法务红线、响应剧本
//
// 未配置时展示 OnboardingWizard(品牌创建表单).

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { mockAccount, mockKeywordGroups, mockKnowledge } from '../../mocks/sentiment';
import { isMockMode } from '../../services/sentimentApi';
import {
  useSentimentAccounts, useUpdateAccount, useDeleteAccount, useRunNow,
  useKnowledge, useUpsertKnowledge, useSentimentPlatforms,
} from '../../hooks/useSentiment';
import type { KeywordGroup, SentimentPlatform } from '../../types/sentiment';

import { TagInput } from '../Dashboard/sentiment/components/TagInput';
import { KeywordGroupsEditor } from '../Dashboard/sentiment/components/KeywordGroupsEditor';
import { KnowledgeEditor } from '../Dashboard/sentiment/components/KnowledgeEditor';
import { OnboardingWizard } from '../Dashboard/sentiment/OnboardingWizard';
import { groupByMediaType } from '../../constants/sentimentPlatforms';

const cardStyle: React.CSSProperties = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border-color)',
};

export function BrandSettingsTab() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const usingMock = isMockMode();

  const accountsQuery = useSentimentAccounts();
  const accounts = accountsQuery.data ?? [];
  const account = usingMock ? mockAccount : accounts[0];

  const updateAccount = useUpdateAccount();
  const deleteAccount = useDeleteAccount();
  const runNowMutation = useRunNow();

  const knowledgeQuery = useKnowledge(usingMock ? null : (account?.id ?? null));
  const upsertKnowledge = useUpsertKnowledge();

  const [target, setTarget] = useState('');
  const [ticker, setTicker] = useState('');
  const [aliases, setAliases] = useState<string[]>([]);
  const [intents, setIntents] = useState<string[]>([]);
  const [keywordGroups, setKeywordGroups] = useState<KeywordGroup[]>([]);
  const [excludes, setExcludes] = useState<string[]>([]);
  const [mediaAllowlist, setMediaAllowlist] = useState<string[]>([]);
  const [emails, setEmails] = useState<string[]>([]);
  const [weixinAlbumUrls, setWeixinAlbumUrls] = useState<string[]>([]);
  const [newsnowSources, setNewsnowSources] = useState<string[]>([]);

  useEffect(() => {
    if (!account) return;
    setTarget(account.target);
    setTicker(account.ticker);
    setAliases(account.aliases ?? []);
    setIntents(account.intent ? account.intent.split(/[,，、;\s]+/).filter(Boolean) : []);
    if (usingMock) {
      setKeywordGroups(mockKeywordGroups);
    } else if (account.keyword_groups && account.keyword_groups.length > 0) {
      setKeywordGroups(account.keyword_groups);
    } else if ((account.keywords ?? []).length > 0) {
      setKeywordGroups([
        { name: '自定义', kind: 'custom', items: account.keywords.map((term) => ({ term })) },
      ]);
    } else {
      setKeywordGroups([]);
    }
    setExcludes(account.excludes ?? []);
    setMediaAllowlist(account.media_allowlist ?? []);
    setEmails(account.notify_emails ?? []);
    setWeixinAlbumUrls(account.weixin_album_urls ?? []);
    setNewsnowSources(account.newsnow_sources ?? []);
  }, [account, usingMock]);

  const knowledgeFromApi = (knowledgeQuery.data ?? []).reduce(
    (acc, k) => ({ ...acc, [k.key]: k.body }),
    { brand_voice: '', legal_redlines: '', response_playbook: '' } as Record<string, string>,
  );
  const [localKnowledge, setLocalKnowledge] = useState(mockKnowledge);

  useEffect(() => {
    if (!usingMock && knowledgeQuery.data) {
      setLocalKnowledge({
        brand_voice: knowledgeFromApi.brand_voice || '',
        legal_redlines: knowledgeFromApi.legal_redlines || '',
        response_playbook: knowledgeFromApi.response_playbook || '',
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [knowledgeQuery.data, usingMock]);

  // 未配置品牌 → 显示创建表单
  if (!usingMock && accountsQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div
          className="animate-spin rounded-full h-8 w-8 border-t-2 border-b-2"
          style={{ borderColor: 'var(--accent-primary)' }}
        />
      </div>
    );
  }

  if (!usingMock && !account) {
    return (
      <OnboardingWizard
        onSubmit={() => {
          accountsQuery.refetch();
        }}
      />
    );
  }

  const buildPayload = () => ({
    target, ticker,
    aliases, intent: intents.length > 0 ? intents.join('、') : undefined,
    keyword_groups: keywordGroups,
    excludes, media_allowlist: mediaAllowlist, notify_emails: emails,
    weixin_album_urls: weixinAlbumUrls,
    newsnow_sources: newsnowSources,
  });

  const persistKnowledge = async () => {
    if (usingMock) return;
    const tasks: Promise<unknown>[] = [];
    for (const key of ['brand_voice', 'legal_redlines', 'response_playbook'] as const) {
      const newBody = localKnowledge[key] ?? '';
      const oldBody = knowledgeFromApi[key] ?? '';
      if (newBody !== oldBody) {
        tasks.push(upsertKnowledge.mutateAsync({ accountId: account!.id, key, body: newBody }));
      }
    }
    await Promise.all(tasks);
  };

  const handleSave = async () => {
    if (usingMock) {
      alert(t('account.brand.saved'));
      return;
    }
    try {
      await updateAccount.mutateAsync({ id: account!.id, payload: buildPayload() });
      await persistKnowledge();
      alert(t('account.brand.saved'));
    } catch (e) {
      alert(`${t('account.brand.saveFailed')}${e instanceof Error ? e.message : e}`);
    }
  };

  const handleSaveAndRun = async () => {
    if (usingMock) {
      alert(`${t('account.brand.saved')}\n${t('account.brand.runNowQueued')}`);
      return;
    }
    try {
      await updateAccount.mutateAsync({ id: account!.id, payload: buildPayload() });
      await persistKnowledge();
      // update 若检测到关键词/intent 变化会自动入队 pipeline,
      // 此时 /run-now 返回 409 是正常的 — 忽略即可.
      try {
        await runNowMutation.mutateAsync(account!.id);
      } catch {
        // 409 = task already running/queued — 不影响保存成功
      }
      alert(`${t('account.brand.saved')}\n${t('account.brand.runNowQueued')}`);
      navigate('/sentiment');
    } catch (e) {
      alert(`${t('account.brand.saveFailed')}${e instanceof Error ? e.message : e}`);
    }
  };

  const handleDelete = async () => {
    if (!confirm(t('account.brand.deleteConfirm'))) return;
    if (usingMock) {
      alert(t('account.brand.deleted'));
      return;
    }
    try {
      await deleteAccount.mutateAsync(account!.id);
      alert(t('account.brand.deleted'));
      accountsQuery.refetch();
    } catch (e) {
      alert(`${t('account.brand.deleteFailed')}${e instanceof Error ? e.message : e}`);
    }
  };

  const saving = updateAccount.isPending || upsertKnowledge.isPending;
  const running = runNowMutation.isPending;

  return (
    <div className="space-y-5">
      {/* ── 区块 1: 品牌信息 ── */}
      <Section title={t('account.brand.sections.brandInfo')}>
        <Grid>
          <Field label={t('account.brand.fields.target')} required>
            <Input value={target} onChange={setTarget} />
          </Field>
          <Field label={t('account.brand.fields.ticker')}>
            <Input value={ticker} onChange={setTicker} mono />
          </Field>
        </Grid>
        <Field label={t('account.brand.fields.aliases')}>
          <TagInput value={aliases} onChange={setAliases} placeholder={t('account.brand.fields.tagPlaceholder')} />
        </Field>
      </Section>

      {/* ── 区块 2: 监控配置 ── */}
      <Section title={t('account.brand.sections.monitoring')}>
        <Field label={t('account.brand.fields.intent')}>
          <TagInput value={intents} onChange={setIntents} placeholder={t('account.brand.fields.intentPlaceholder')}
            suggestions={['做空报告', '业绩传闻', '高管变动', '海外业务', '竞品动态', '政策监管', '诉讼纠纷', '股价异动']} />
        </Field>
        <KeywordGroupsEditor value={keywordGroups} onChange={setKeywordGroups} />
        <Field label={t('account.brand.fields.excludes')}>
          <TagInput value={excludes} onChange={setExcludes} placeholder={t('account.brand.fields.tagPlaceholder')} />
        </Field>
        <Field label={t('account.brand.fields.mediaAllowlist')}>
          <MediaAllowlistEditor value={mediaAllowlist} onChange={setMediaAllowlist} />
        </Field>
      </Section>

      {/* ── 区块 2.5: 扩展数据源(可选,默认关闭) ── */}
      <Section title={t('account.brand.sections.extraSources', '扩展数据源(可选)')}>
        <Field label={t('account.brand.fields.weixinAlbumUrls', '微信公众号合集 URL')}>
          <TagInput
            value={weixinAlbumUrls}
            onChange={setWeixinAlbumUrls}
            placeholder="https://mp.weixin.qq.com/mp/appmsgalbum?__biz=...&album_id=..."
            max={20}
          />
          <p className="text-[11px] mt-1.5" style={{ color: 'var(--text-muted)' }}>
            周级别盯防几个高价值公众号(竞品官号 / 行业 KOL / 监管口径号)。
            粘贴合集 URL 即可,无 cookie。空 = 不启用。
          </p>
        </Field>
        <Field label={t('account.brand.fields.newsnowSources', 'NewsNow 热榜源订阅')}>
          <TagInput
            value={newsnowSources}
            onChange={setNewsnowSources}
            placeholder="weibo / zhihu / v2ex / hupu / toutiao / ithome / ..."
            suggestions={['weibo', 'zhihu', 'v2ex', 'hupu', 'toutiao', 'ithome', 'douban', 'juejin', '36kr']}
          />
          <p className="text-[11px] mt-1.5" style={{ color: 'var(--text-muted)' }}>
            从自托管 newsnow 容器拉热榜,本地按品牌名 + 别名 + 关键词过滤标题。
            空 = 不启用。
          </p>
        </Field>
      </Section>

      {/* ── 区块 3: 通知设置 ── */}
      <Section title={t('account.brand.sections.notify')}>
        <Field label={t('account.brand.fields.emails')}>
          <TagInput value={emails} onChange={setEmails} placeholder="ir@yourcompany.com" max={10} />
        </Field>
      </Section>

      {/* ── 区块 4: 知识库 ── */}
      <Section title={t('account.brand.sections.knowledge')}>
        <KnowledgeEditor knowledge={localKnowledge} onChange={setLocalKnowledge} />
      </Section>

      {/* ── 操作栏 ── */}
      <section className="rounded-2xl p-5 flex items-center justify-between flex-wrap gap-3" style={cardStyle}>
        <div className="flex gap-2">
          <button type="button" onClick={handleSave} disabled={saving}
            className="rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-50"
            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-primary)' }}>
            {saving ? '...' : t('account.brand.save')}
          </button>
          <button type="button" onClick={handleSaveAndRun} disabled={saving || running}
            className="btn-solid rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-50">
            {(saving || running) ? '...' : t('account.brand.saveAndRun')}
          </button>
        </div>
        <button type="button" onClick={handleDelete}
          className="text-xs font-semibold" style={{ color: '#dc2626' }}>
          {t('account.brand.delete')}
        </button>
      </section>
    </div>
  );
}

/* ── 本地 UI 组件 ── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl p-5 space-y-3" style={cardStyle}>
      <h2 className="text-sm font-semibold text-primary uppercase tracking-wide">{title}</h2>
      {children}
    </section>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="text-xs font-semibold text-secondary uppercase tracking-wider block mb-1.5">
        {label} {required && <span style={{ color: '#dc2626' }}>*</span>}
      </label>
      {children}
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{children}</div>;
}

function Input({ value, onChange, mono }: { value: string; onChange: (v: string) => void; mono?: boolean }) {
  return (
    <input type="text" value={value} onChange={(e) => onChange(e.target.value)}
      className={`w-full px-3 py-2 rounded text-sm ${mono ? 'font-mono' : ''}`}
      style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
  );
}

/* ── 媒体白名单分组编辑器 — 参照 WisersOne 的"媒体类型"轴(网媒/微博/微信/
   APP/论坛/短视频/长视频/...),每组一行小标题 + chip + 全选/清空。
   平台目录从 useSentimentPlatforms() 拉,DB 是 single source of truth。

   value 语义:`[]` = 全部平台(canonical "all"),非空数组 = 仅勾选的子集。
   折叠态默认隐藏 chip 区,只展示"高级选择"入口 + 当前状态摘要。 */
function MediaAllowlistEditor({
  value, onChange,
}: { value: string[]; onChange: (next: string[]) => void }) {
  const { t, i18n } = useTranslation();
  const platformsQuery = useSentimentPlatforms();
  const platforms = platformsQuery.data ?? [];
  const groups = groupByMediaType(platforms);
  const allCodes = useMemo(() => platforms.map(p => p.code), [platforms]);
  const total = allCodes.length;

  const [expanded, setExpanded] = useState(false);
  // 每个媒体类型分组独立折叠 — 默认全部折叠,避免一展开就刷出 70+ chip。
  // 用户点小箭头才展开对应组。
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set());
  const toggleGroup = (mt: string) => {
    setOpenGroups(prev => {
      const next = new Set(prev);
      if (next.has(mt)) next.delete(mt); else next.add(mt);
      return next;
    });
  };

  // value=[] 视为"全选"——chip 全亮,但保持后端语义不变(空数组 = 全部)。
  const isAll = value.length === 0;
  const effective = isAll ? allCodes : value;
  const selectedSet = useMemo(() => new Set(effective), [effective]);

  // 写回:全部勾上时 normalize 回 `[]`,与"留空 = 全部"对齐。
  const commit = (next: string[]) => {
    if (next.length === total && allCodes.every(c => next.includes(c))) {
      onChange([]);
    } else {
      onChange(next);
    }
  };

  const toggle = (code: string) => {
    if (selectedSet.has(code)) commit(effective.filter(c => c !== code));
    else commit([...effective, code]);
  };
  const setGroup = (codes: string[], select: boolean) => {
    const set = new Set(effective);
    for (const c of codes) {
      if (select) set.add(c); else set.delete(c);
    }
    commit(Array.from(set));
  };
  // 优先 DB 里的本地化名;空再回 i18n sourceLabels;再回 code。
  const platformLabel = (p: SentimentPlatform): string => {
    const fromDb = i18n.language === 'zh' ? p.name_zh : p.name_en;
    if (fromDb) return fromDb;
    const k = `dashboard.sentiment.articles.sourceLabels.${p.code}`;
    const v = t(k);
    return v === k ? p.code : v;
  };

  const status = isAll
    ? t('account.brand.fields.mediaAllowlistAllOn', { total })
    : t('account.brand.fields.mediaAllowlistPartialStatus', { count: value.length, total });

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={() => setExpanded(v => !v)}
          className="text-xs font-semibold inline-flex items-center gap-1 hover:text-primary"
          style={{ color: 'var(--text-secondary)' }}
        >
          <span style={{ display: 'inline-block', width: 10 }}>{expanded ? '▾' : '▸'}</span>
          {t('account.brand.fields.mediaAllowlistAdvanced')}
        </button>
        <span className="text-[11px] text-muted">{status}</span>
        {expanded && !isAll && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="ml-auto text-[11px] text-muted hover:text-primary"
          >
            {t('account.brand.fields.mediaAllowlistReset')}
          </button>
        )}
      </div>

      {expanded && (
        <div className="space-y-2">
          <p className="text-xs text-muted">
            {t('account.brand.fields.mediaAllowlistHint')}
          </p>
          <div
            className="rounded-md divide-y"
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-color)',
              borderColor: 'var(--border-color)',
            }}
          >
            {groups.map(({ mediaType, items }) => {
              const codes = items.map(i => i.code);
              const selectedCount = codes.filter(c => selectedSet.has(c)).length;
              const allOn = selectedCount === codes.length;
              const open = openGroups.has(mediaType);
              return (
                <div key={mediaType}>
                  {/* 行头:点 caret/标题展开,右侧"全选/清空"按钮独立 */}
                  <div className="flex items-center gap-2 px-3 py-2">
                    <button
                      type="button"
                      onClick={() => toggleGroup(mediaType)}
                      className="flex items-center gap-2 flex-1 min-w-0 text-left hover:text-primary"
                      style={{ color: 'var(--text-secondary)' }}
                    >
                      <span style={{ display: 'inline-block', width: 10, fontSize: 10 }}>
                        {open ? '▾' : '▸'}
                      </span>
                      <span className="text-xs font-semibold uppercase tracking-wider truncate">
                        {t(`dashboard.sentiment.articles.mediaTypes.${mediaType}`)}
                      </span>
                      <span className="text-[11px] font-normal normal-case text-muted">
                        {selectedCount > 0 && selectedCount < codes.length
                          ? `${selectedCount}/${codes.length}`
                          : codes.length}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setGroup(codes, !allOn); }}
                      className="text-[11px] text-muted hover:text-primary whitespace-nowrap"
                    >
                      {allOn
                        ? t('account.brand.fields.mediaAllowlistClearGroup')
                        : t('account.brand.fields.mediaAllowlistSelectGroup')}
                    </button>
                  </div>
                  {/* 平台列表 — 竖列 list 项,平台增多时也不会撑爆宽度;
                     超过 ~16 项限高滚动,选中行用浅蓝底 + ✓ 标记。 */}
                  {open && (
                    <div
                      className={`flex flex-col ${items.length > 16 ? 'max-h-72 overflow-y-auto' : ''}`}
                      style={{ borderTop: '1px solid var(--border-color)' }}
                    >
                      {items.map((p, idx) => {
                        const active = selectedSet.has(p.code);
                        const label = platformLabel(p);
                        return (
                          <button
                            key={p.code}
                            type="button"
                            onClick={() => toggle(p.code)}
                            title={label}
                            className="flex items-center justify-between text-xs px-3 py-1.5 transition-colors text-left"
                            style={{
                              background: active ? 'rgba(99,102,241,0.10)' : 'transparent',
                              color: active ? 'var(--accent-primary)' : 'var(--text-secondary)',
                              borderTop: idx === 0 ? 'none' : '1px solid var(--border-color)',
                            }}
                          >
                            <span className="truncate">{label}</span>
                            <span
                              className="ml-2 text-[11px]"
                              style={{ color: active ? 'var(--accent-primary)' : 'var(--text-muted)' }}
                            >
                              {active ? '✓' : ''}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
