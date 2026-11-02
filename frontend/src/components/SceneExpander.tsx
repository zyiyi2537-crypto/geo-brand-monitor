// 2026-05-28 — 4 维场景扩展组件.
// 单 seed 输入 + 4 个 scene 复选框(默认全勾)+ [拓词] 按钮.
// 拓词后下面渲染 4 个 tab,各 tab 内列出该场景产出的候选 query.
// 选词回调到外层(由外层决定送 probe / 入选监测问题).

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { SceneType } from '../services/aiTelemetryApi';
import { ALL_SCENES } from '../services/aiTelemetryApi';
import type { ExpandQueriesResp } from '../services/topicProfileApi';

interface Props {
  /** 当前 topic 是否要求 target(品牌名)非空 —— brand 场景在 target 为空时灰显 */
  brandSceneAvailable: boolean;
  /** 拓词回调,由父组件决定调哪个 API client.返回 v2 response. */
  onExpand: (seed: string, scenes: SceneType[], countPerScene: number) => Promise<ExpandQueriesResp>;
  /** 用户在某 scene tab 内勾了一个 candidate query,父组件负责落库 */
  onPickCandidate: (text: string, scene: SceneType, seed: string) => void;
  /** 已勾选 set(用于在 candidate list 上回显勾选状态) */
  selectedSet: Set<string>;
  /** 拓词后从外层透传 readonly,防止已提交审核状态下还能改 */
  readOnly?: boolean;
  /** 每场景默认产出条数,默认 50(后端上限) */
  defaultCountPerScene?: number;
}

// 当前一次拓词的产出 — 按 scene 分组
interface RunState {
  seed: string;
  results: Partial<Record<SceneType, { queries: string[]; error?: string | null }>>;
}

export function SceneExpander({
  brandSceneAvailable,
  onExpand,
  onPickCandidate,
  selectedSet,
  readOnly = false,
  defaultCountPerScene = 50,
}: Props) {
  const { t } = useTranslation();
  const [seed, setSeed] = useState('');
  const [enabledScenes, setEnabledScenes] = useState<Set<SceneType>>(
    () => new Set<SceneType>(ALL_SCENES.filter(s => s !== 'brand' || brandSceneAvailable)),
  );
  const [countPerScene, setCountPerScene] = useState(defaultCountPerScene);
  const [run, setRun] = useState<RunState | null>(null);
  const [activeTab, setActiveTab] = useState<SceneType>('search');
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const toggleScene = (s: SceneType) => {
    if (s === 'brand' && !brandSceneAvailable) return;
    const next = new Set(enabledScenes);
    if (next.has(s)) next.delete(s);
    else next.add(s);
    setEnabledScenes(next);
  };

  const handleExpand = async () => {
    const seedTrim = seed.trim();
    if (!seedTrim || loading) return;
    if (enabledScenes.size === 0) {
      setErr(t('topic.profile.monitor.scene.pickAtLeastOne'));
      return;
    }
    setLoading(true); setErr(null);
    try {
      const resp = await onExpand(seedTrim, Array.from(enabledScenes), countPerScene);
      const sceneMap = resp.scenes || {};
      // 老 schema fallback:如果只有 .queries 数组没有 .scenes,把它当 search 场景
      const compatScenes: RunState['results'] = {};
      if (Object.keys(sceneMap).length === 0 && Array.isArray(resp.queries)) {
        compatScenes.search = { queries: resp.queries };
      } else {
        for (const s of ALL_SCENES) {
          const v = sceneMap[s];
          if (v) compatScenes[s] = { queries: v.queries || [], error: v.error || null };
        }
      }
      setRun({ seed: seedTrim, results: compatScenes });
      // 自动切到第一个有产出的 tab
      const firstNonEmpty = ALL_SCENES.find(s => (compatScenes[s]?.queries.length || 0) > 0);
      if (firstNonEmpty) setActiveTab(firstNonEmpty);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="rounded-md p-3 space-y-3"
         style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <p className="text-sm font-semibold text-primary">
        {t('topic.profile.monitor.scene.title')}
      </p>
      <p className="text-xs text-muted">
        {t('topic.profile.monitor.scene.hint')}
      </p>

      {!readOnly && (
        <>
          <div className="flex gap-2 flex-wrap items-center">
            <input type="text" value={seed} onChange={e => setSeed(e.target.value)}
                   placeholder={t('topic.profile.monitor.seedPlaceholder')}
                   className="flex-1 min-w-[180px] text-sm px-3 py-2 rounded-md"
                   style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                            border: '1px solid var(--border-color)' }} />
            <input type="number" min={5} max={50} value={countPerScene}
                   onChange={e => setCountPerScene(Math.min(50, Math.max(5, +e.target.value || 50)))}
                   title={t('topic.profile.monitor.scene.countPerSceneHint')}
                   className="w-20 text-sm px-3 py-2 rounded-md"
                   style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                            border: '1px solid var(--border-color)' }} />
            <button type="button" onClick={handleExpand} disabled={loading || !seed.trim() || enabledScenes.size === 0}
                    className="text-sm px-4 py-2 rounded-md text-white"
                    style={{ background: 'var(--accent-primary)',
                             opacity: (loading || !seed.trim() || enabledScenes.size === 0) ? 0.5 : 1 }}>
              {loading ? t('topic.profile.monitor.scene.expanding') : t('topic.profile.monitor.scene.expand')}
            </button>
          </div>

          <div className="flex gap-3 flex-wrap items-center text-xs">
            <span className="text-muted">{t('topic.profile.monitor.scene.dimensions')}</span>
            {ALL_SCENES.map(s => {
              const disabled = s === 'brand' && !brandSceneAvailable;
              const checked = enabledScenes.has(s) && !disabled;
              return (
                <label key={s}
                       className="inline-flex items-center gap-1.5 cursor-pointer"
                       style={{ opacity: disabled ? 0.4 : 1, cursor: disabled ? 'not-allowed' : 'pointer' }}
                       title={disabled ? t('topic.profile.monitor.scene.brand.disabledHint') : ''}>
                  <input type="checkbox" checked={checked} disabled={disabled}
                         onChange={() => toggleScene(s)}
                         style={{ accentColor: 'var(--accent-primary)' }} />
                  <span className="text-primary">
                    {t(`topic.profile.monitor.scene.${s}.label`)}
                  </span>
                </label>
              );
            })}
          </div>
        </>
      )}

      {err && <div className="text-xs" style={{ color: '#ef4444' }}>{err}</div>}

      {run && (
        <div className="space-y-2">
          <div className="text-xs text-muted">
            {t('topic.profile.monitor.scene.resultFor', { seed: run.seed })}
          </div>
          <div className="flex gap-1 flex-wrap border-b" style={{ borderColor: 'var(--border-color)' }}>
            {ALL_SCENES.map(s => {
              const r = run.results[s];
              const count = r?.queries.length || 0;
              const hasErr = !!r?.error;
              const isActive = s === activeTab;
              const isAvailable = !!r; // 该 scene 这次有跑过(可能 count=0 + error)
              return (
                <button key={s}
                        onClick={() => isAvailable && setActiveTab(s)}
                        disabled={!isAvailable}
                        className="text-xs px-3 py-1.5 rounded-t-md"
                        style={{
                          background: isActive ? 'var(--bg-tertiary)' : 'transparent',
                          color: hasErr ? '#ef4444' : isActive ? 'var(--accent-primary)' : 'var(--text-secondary)',
                          borderBottom: isActive ? '2px solid var(--accent-primary)' : 'none',
                          opacity: isAvailable ? 1 : 0.4,
                          cursor: isAvailable ? 'pointer' : 'not-allowed',
                        }}>
                  {t(`topic.profile.monitor.scene.${s}.label`)}
                  <span className="ml-1.5 inline-block px-1.5 py-0.5 rounded-full text-[10px]"
                        style={{
                          background: isActive ? 'var(--accent-primary)' : 'var(--bg-card)',
                          color: isActive ? '#fff' : 'var(--text-muted)',
                        }}>
                    {hasErr ? '!' : count}
                  </span>
                </button>
              );
            })}
          </div>

          <SceneCandidateList
            scene={activeTab}
            seed={run.seed}
            data={run.results[activeTab]}
            selectedSet={selectedSet}
            onPick={onPickCandidate}
            readOnly={readOnly}
          />
        </div>
      )}
    </div>
  );
}

function SceneCandidateList({
  scene, seed, data, selectedSet, onPick, readOnly,
}: {
  scene: SceneType;
  seed: string;
  data: { queries: string[]; error?: string | null } | undefined;
  selectedSet: Set<string>;
  onPick: (text: string, scene: SceneType, seed: string) => void;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  if (!data) {
    return (
      <div className="text-xs text-muted py-4 text-center">
        {t('topic.profile.monitor.scene.notRun')}
      </div>
    );
  }
  if (data.error) {
    return (
      <div className="text-xs py-4 px-3 rounded-md"
           style={{ background: 'rgba(239,68,68,0.08)', color: '#ef4444' }}>
        {data.error}
      </div>
    );
  }
  if (data.queries.length === 0) {
    return (
      <div className="text-xs text-muted py-4 text-center">
        {t('topic.profile.monitor.scene.empty')}
      </div>
    );
  }
  return (
    <div className="space-y-1.5 max-h-[360px] overflow-y-auto pr-1">
      {data.queries.map(q => {
        const checked = selectedSet.has(q);
        return (
          <label key={q}
                 className="flex items-start gap-2 p-2 rounded-md cursor-pointer"
                 style={{
                   background: checked ? 'var(--bg-tertiary)' : 'var(--bg-card)',
                   border: `1px solid ${checked ? 'var(--accent-primary)' : 'var(--border-color)'}`,
                   opacity: readOnly ? 0.6 : 1,
                 }}>
            <input type="checkbox" checked={checked} disabled={readOnly}
                   onChange={() => onPick(q, scene, seed)}
                   className="mt-0.5"
                   style={{ accentColor: 'var(--accent-primary)' }} />
            <span className="text-sm text-primary flex-1">{q}</span>
          </label>
        );
      })}
    </div>
  );
}
