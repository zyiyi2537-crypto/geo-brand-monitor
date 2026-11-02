// 品牌资料表单 — TopicEditor 和 /dashboard/topics/:id/profile 共用.
//
// 字段定义见 services/aiTelemetryApi.ts 的 BrandProfile.
// 必填项校验在调用方传 requiredKeys 控制(因为 admin 编辑器 vs 用户提交审核要求不同).
//
// 2026-05-18:
//   - 5 节由竖排改为顶部 tab 切换,缩短单页长度
//   - 别名(target_aliases)从外层独立 section 移入「基础标识」tab,
//     调用方可选传 `aliases` + `onAliasesChange`(只有 TopicEditor 用)

import { useState } from 'react';
import type { BrandProfile } from '../services/aiTelemetryApi';

// 用户提交审核时必填的核心字段(跟后端 PROFILE_REQUIRED_FIELDS 对齐)
// 二、内容创作方向(creation_directions / copywriting_types / target_platforms /
// content_tones / content_redlines)整节移除 — 这些由内容审核 / 投放策略阶段
// 决定,不在资料表单里强制填。BrandProfile schema 字段保留(老数据不破),
// content_generator 的 prompt 拼装如果读到空就跳过。
// 2026-05-17 起 — 只把「一、基础标识」节的 6 个字段卡成必填.
// 2026-05-27:core_business_lines 退出必填 — 实践里很多场景一句话讲清楚业务线
// 写在 industry 里就够,空着也允许跑通.其余 5 个仍必填.
// 其他模块都是「素材库」性质,鼓励多填但不卡死;LLM 拿到什么用什么.
export const PROFILE_REQUIRED_FIELDS: (keyof BrandProfile)[] = [
  'profile_name', 'company_full_name', 'company_short_name',
  'industry', 'service_geo',
];

export function isProfileFieldFilled(profile: BrandProfile, key: keyof BrandProfile): boolean {
  const v = profile[key] as string | string[];
  if (Array.isArray(v)) return v.length > 0;
  return !!(v && v.trim());
}

export function profileMissingFields(profile: BrandProfile, required = PROFILE_REQUIRED_FIELDS): (keyof BrandProfile)[] {
  return required.filter(k => !isProfileFieldFilled(profile, k));
}

// 主体类型 — 单选,驱动扩展词风格(与后端 query_expander.ENTITY_TYPE_HINTS 同 key)。
// 资料抽取时 AI 自动判,用户可改;空 = 未判定,扩展按通用模板跑。
const ENTITY_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: 'service_tool',  label: '服务工具' },
  { value: 'manufacturer',  label: '生产制造商' },
  { value: 'brand_owner',   label: '品牌方' },
  { value: 'other',         label: '其他' },
];

type SectionKey = 'basic' | 'subject' | 'service' | 'story' | 'extra' | 'creation';

const SECTIONS: { key: SectionKey; label: string }[] = [
  { key: 'basic',    label: '一、基础标识' },
  { key: 'subject',  label: '二、品牌主体信息' },
  { key: 'service',  label: '三、产品 / 服务核心信息' },
  { key: 'story',    label: '四、品牌故事与情感素材' },
  { key: 'extra',    label: '五、补充素材与创作边界' },
  { key: 'creation', label: '六、内容创作偏好' },
];

// 2026-05-28 — 创作方向 / 文案类型 候选值(与后端 content_generator.DIRECTION_HINTS /
// TYPE_HINTS 同 key).多选,选了几个 → 同一条 query 出几篇风格不同的稿件.
const CREATION_DIRECTION_OPTIONS: { value: string; label: string; desc: string }[] = [
  { value: 'industry_insight',  label: '行业洞察',  desc: '趋势 / 市场数据 / 头部玩家' },
  { value: 'case_story',        label: '案例分享',  desc: '真实项目复盘' },
  { value: 'how_to_guide',      label: '实操指南',  desc: '步骤化 / 怎么做' },
  { value: 'trend_forecast',    label: '趋势预测',  desc: '行业前瞻 + 应对' },
  { value: 'product_review',    label: '产品评测',  desc: '横向对比 / 优劣矩阵' },
  { value: 'customer_story',    label: '客户故事',  desc: '第一人称 + 量化成果' },
  { value: 'faq',               label: 'FAQ 答疑', desc: '常见问题列表' },
];

const COPYWRITING_TYPE_OPTIONS: { value: string; label: string; desc: string }[] = [
  { value: 'long_form',          label: '深度长文',     desc: '1500-2500 字 · 公众号 / 知乎' },
  { value: 'medium_post',        label: '中等图文',     desc: '500-1500 字 · 公众号中等' },
  { value: 'short_social',       label: '短社媒文案',   desc: '<500 字 · 小红书 / 微博' },
  { value: 'video_script_long',  label: '长视频脚本',   desc: '5-8 分钟口播稿' },
  { value: 'video_script_short', label: '短视频文案',   desc: '30-60 秒口播稿' },
  { value: 'faq_list',           label: 'FAQ 列表',     desc: '8-12 条 Q&A' },
];

interface ProfileFormProps {
  profile: BrandProfile;
  onChange: (p: BrandProfile) => void;
  readOnly?: boolean;
  requiredKeys?: (keyof BrandProfile)[];
  // 别名(可选)— 仅 TopicEditor 用;不传则不在「基础标识」里渲染别名输入。
  // 用文本(逗号 / 换行分隔)是因为外层就是这么持久化的,直接复用语义,
  // 父组件 split → string[] 自己负责。
  aliasesText?: string;
  onAliasesTextChange?: (v: string) => void;
  aliasesCount?: number;
  aliasesLabel?: string;
  aliasesPlaceholder?: string;
  aliasesHint?: string;
}

export function BrandProfileForm({
  profile, onChange, readOnly = false, requiredKeys = PROFILE_REQUIRED_FIELDS,
  aliasesText, onAliasesTextChange, aliasesCount,
  aliasesLabel, aliasesPlaceholder, aliasesHint,
}: ProfileFormProps) {
  const req = new Set(requiredKeys);
  const setField = <K extends keyof BrandProfile>(key: K, value: BrandProfile[K]) => {
    onChange({ ...profile, [key]: value });
  };
  const [tab, setTab] = useState<SectionKey>('basic');
  const showAliases = typeof aliasesText === 'string' && typeof onAliasesTextChange === 'function';

  return (
    <div className="space-y-3">
      <div className="flex gap-1 border-b overflow-x-auto"
           style={{ borderColor: 'var(--border-color)' }}>
        {SECTIONS.map(s => (
          <button key={s.key} type="button" onClick={() => setTab(s.key)}
                  className="px-3 py-2 text-sm whitespace-nowrap -mb-px"
                  style={{
                    borderBottom: tab === s.key ? '2px solid var(--accent-primary)' : '2px solid transparent',
                    color: tab === s.key ? 'var(--accent-primary)' : 'var(--text-secondary)',
                  }}>
            {s.label}
          </button>
        ))}
      </div>

      <section className="rounded-md p-4"
               style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="space-y-3">
          {tab === 'basic' && (
            <>
              <Pair>
                <TextRow label="名称" required={req.has('profile_name')} readOnly={readOnly}
                         value={profile.profile_name} onChange={v => setField('profile_name', v)} />
                <TextRow label="公司 / 品牌全称" required={req.has('company_full_name')} readOnly={readOnly}
                         value={profile.company_full_name} onChange={v => setField('company_full_name', v)} />
              </Pair>
              <Pair>
                <TextRow label="公司 / 品牌简称" required={req.has('company_short_name')} readOnly={readOnly}
                         value={profile.company_short_name} onChange={v => setField('company_short_name', v)} />
                <TextRow label="所属行业 / 赛道" required={req.has('industry')} readOnly={readOnly}
                         value={profile.industry} onChange={v => setField('industry', v)} />
              </Pair>
              <SegmentedRow
                label="主体类型"
                aiBadge
                options={ENTITY_TYPE_OPTIONS}
                value={profile.entity_type}
                onChange={v => setField('entity_type', v)}
                readOnly={readOnly}
              />
              <Pair>
                <TextRow label="服务地域" required={req.has('service_geo')} readOnly={readOnly}
                         value={profile.service_geo} onChange={v => setField('service_geo', v)} />
                <TextRow label="品牌官网(选填)" required={false} readOnly={readOnly}
                         value={profile.website || ''} onChange={v => setField('website', v)} />
              </Pair>
              <ParagraphRow label="核心业务线" required={req.has('core_business_lines')} readOnly={readOnly}
                            value={profile.core_business_lines} onChange={v => setField('core_business_lines', v)} />
              {showAliases && (
                <div>
                  <Label text={aliasesLabel || '别名 / 简称(逗号分隔,最多 10 个)'} required={false} />
                  <input type="text" disabled={readOnly}
                         value={aliasesText}
                         onChange={e => onAliasesTextChange!(e.target.value)}
                         placeholder={aliasesPlaceholder}
                         className="w-full text-sm px-3 py-2 rounded-md"
                         style={{
                           background: 'var(--bg-input)', color: 'var(--text-primary)',
                           border: '1px solid var(--border-color)',
                           opacity: readOnly ? 0.6 : 1,
                         }} />
                  {(aliasesHint || typeof aliasesCount === 'number') && (
                    <span className="block mt-1 text-xs text-muted">
                      {aliasesHint || `已识别 ${aliasesCount} 个别名`}
                    </span>
                  )}
                </div>
              )}
            </>
          )}

          {tab === 'subject' && (
            <>
              <Pair>
                <TextRow label="公司 / 团队规模(选填)" required={false} readOnly={readOnly}
                         value={profile.team_size} onChange={v => setField('team_size', v)} />
                <TextRow label="成立时间 / 从业年限" required={req.has('founded_year')} readOnly={readOnly}
                         value={profile.founded_year} onChange={v => setField('founded_year', v)} />
              </Pair>
              <ParagraphRow label="核心荣誉 / 背书资质" required={req.has('core_credentials')} readOnly={readOnly}
                            value={profile.core_credentials} onChange={v => setField('core_credentials', v)} />
              <TagsRow label="品牌差异化标签(3-5 个)" required={req.has('brand_diff_tags')} readOnly={readOnly}
                       value={profile.brand_diff_tags} onChange={v => setField('brand_diff_tags', v)} />
            </>
          )}

          {tab === 'service' && (
            <>
              <TextAreaRow label="核心服务概述" required={req.has('core_service_overview')} readOnly={readOnly}
                           value={profile.core_service_overview} onChange={v => setField('core_service_overview', v)} />
              <ParagraphRow label="服务核心特点" required={req.has('service_features')} readOnly={readOnly}
                            value={profile.service_features} onChange={v => setField('service_features', v)} />
              <ParagraphRow label="服务关键流程 / 环节" required={req.has('service_process')} readOnly={readOnly}
                            value={profile.service_process} onChange={v => setField('service_process', v)} />
              <ParagraphRow label="服务覆盖场景 / 客户类型" required={req.has('target_scenarios')} readOnly={readOnly}
                            value={profile.target_scenarios} onChange={v => setField('target_scenarios', v)} />
              <TagsRow label="服务交付保障(选填)" required={false} readOnly={readOnly}
                       value={profile.service_guarantees} onChange={v => setField('service_guarantees', v)} />
            </>
          )}

          {tab === 'story' && (
            <>
              <TextAreaRow label="品牌故事 / 成立初衷" required={req.has('brand_story')} readOnly={readOnly}
                           value={profile.brand_story} onChange={v => setField('brand_story', v)} />
              <TextAreaRow label="核心人物故事(选填)" required={false} readOnly={readOnly}
                           value={profile.key_person_story} onChange={v => setField('key_person_story', v)} />
              <ParagraphRow label="典型案例 / 客户故事(脱敏)(选填)" required={false} readOnly={readOnly}
                            value={profile.case_stories} onChange={v => setField('case_stories', v)} />
              <TextAreaRow label="品牌价值观 / 服务理念" required={req.has('brand_values')} readOnly={readOnly}
                           value={profile.brand_values} onChange={v => setField('brand_values', v)} />
            </>
          )}

          {tab === 'extra' && (
            <>
              <Pair>
                <TextRow label="品牌 Slogan / 宣传语(选填)" required={false} readOnly={readOnly}
                         value={profile.brand_slogan} onChange={v => setField('brand_slogan', v)} />
                <span />
              </Pair>
              <TagsRow label="可提供的素材类型(选填)" required={false} readOnly={readOnly}
                       value={profile.available_materials} onChange={v => setField('available_materials', v)} />
              <TextAreaRow label="本次内容想传递的核心信息" required={req.has('core_message')} readOnly={readOnly}
                           value={profile.core_message} onChange={v => setField('core_message', v)} />
              <TextAreaRow label="其他补充说明(选填)" required={false} readOnly={readOnly}
                           value={profile.extra_notes} onChange={v => setField('extra_notes', v)} />
            </>
          )}
          {tab === 'creation' && (
            <>
              <div className="text-xs text-muted -mt-1 mb-2 leading-relaxed"
                   style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)',
                            padding: '8px 12px', borderRadius: 6 }}>
                选了几个「创作方向」× 几个「文案类型」,系统就为每条监测问题
                <strong style={{ color: 'var(--accent-primary)' }}> 出几篇风格不同的稿件 </strong>。
                例如:勾「案例分享 + 实操指南」× 「深度长文 + 短社媒」= 同一问题 4 篇稿。
                上限 9 篇/问题(超过自动截断);两边都不选 → 沿用旧行为(每问题 1 篇)。
              </div>
              <OptionsMultiRow
                label="创作方向(多选)"
                options={CREATION_DIRECTION_OPTIONS}
                value={profile.creation_directions}
                onChange={v => setField('creation_directions', v)}
                readOnly={readOnly}
              />
              <OptionsMultiRow
                label="文案类型(多选)"
                options={COPYWRITING_TYPE_OPTIONS}
                value={profile.copywriting_types}
                onChange={v => setField('copywriting_types', v)}
                readOnly={readOnly}
              />
            </>
          )}
        </div>
      </section>
    </div>
  );
}

function Pair({ children }: { children: React.ReactNode }) {
  // md+ 两列网格,sm 单列。空槽位塞 <span /> 占位即可
  return <div className="grid grid-cols-1 md:grid-cols-2 gap-3">{children}</div>;
}

function Label({ text, required }: { text: string; required: boolean }) {
  return (
    <label className="block text-xs text-secondary mb-1">
      {text}{required && <span style={{ color: '#ef4444' }}> *</span>}
    </label>
  );
}

interface TextProps {
  label: string; required: boolean; readOnly: boolean;
  value: string; onChange: (v: string) => void; placeholder?: string;
}

function TextRow({ label, required, readOnly, value, onChange, placeholder }: TextProps) {
  return (
    <div>
      <Label text={label} required={required} />
      <input type="text" disabled={readOnly}
             className="w-full text-sm px-3 py-2 rounded-md"
             style={{
               background: 'var(--bg-input)', color: 'var(--text-primary)',
               border: '1px solid var(--border-color)',
               opacity: readOnly ? 0.6 : 1,
             }}
             value={value} placeholder={placeholder}
             onChange={e => onChange(e.target.value)} />
    </div>
  );
}

function TextAreaRow({ label, required, readOnly, value, onChange }: TextProps) {
  return (
    <div>
      <Label text={label} required={required} />
      <textarea disabled={readOnly}
                rows={3}
                className="w-full text-sm px-3 py-2 rounded-md"
                style={{
                  background: 'var(--bg-input)', color: 'var(--text-primary)',
                  border: '1px solid var(--border-color)',
                  opacity: readOnly ? 0.6 : 1,
                }}
                value={value}
                onChange={e => onChange(e.target.value)} />
    </div>
  );
}

// 整段文本编辑,底层仍存 string[](保持 schema 兼容).
// 加载:多 item 数组用换行连起来展示;
// 保存:整段文本 trim 后作为 string[] 的唯一元素回写,空则存 [].
// 这样下游 LLM prompt 拼装(把数组按行拼)行为不变,只是把"用户手动维护多条"
// 改成了"整段文本"输入体验.
interface ParagraphProps {
  label: string; required: boolean; readOnly: boolean;
  value: string[]; onChange: (v: string[]) => void; rows?: number;
}

function ParagraphRow({ label, required, readOnly, value, onChange, rows = 4 }: ParagraphProps) {
  const text = value.join('\n');
  return (
    <div>
      <Label text={label} required={required} />
      <textarea disabled={readOnly}
                rows={rows}
                className="w-full text-sm px-3 py-2 rounded-md"
                style={{
                  background: 'var(--bg-input)', color: 'var(--text-primary)',
                  border: '1px solid var(--border-color)',
                  opacity: readOnly ? 0.6 : 1,
                }}
                value={text}
                onChange={e => {
                  const v = e.target.value;
                  onChange(v.trim() ? [v] : []);
                }} />
    </div>
  );
}

interface TagsProps {
  label: string; required: boolean; readOnly: boolean;
  value: string[]; onChange: (v: string[]) => void; placeholder?: string;
}

// 2026-05-28 — 多选 chip 行,选项是固定枚举(创作方向 / 文案类型);跟 TagsRow 的
// 自由输入不同,这里是「点 chip 切换勾选」.每个 chip 下方带简短描述.
function OptionsMultiRow({
  label, options, value, onChange, readOnly,
}: {
  label: string;
  options: { value: string; label: string; desc: string }[];
  value: string[];
  onChange: (v: string[]) => void;
  readOnly: boolean;
}) {
  const set = new Set(value || []);
  const toggle = (v: string) => {
    const next = new Set(set);
    if (next.has(v)) next.delete(v); else next.add(v);
    onChange(Array.from(next));
  };
  return (
    <div>
      <Label text={label} required={false} />
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
        {options.map(opt => {
          const checked = set.has(opt.value);
          return (
            <button
              key={opt.value}
              type="button"
              disabled={readOnly}
              onClick={() => toggle(opt.value)}
              className="text-left px-3 py-2 rounded-md border"
              style={{
                background: checked ? 'var(--bg-tertiary)' : 'var(--bg-card)',
                borderColor: checked ? 'var(--accent-primary)' : 'var(--border-color)',
                color: 'var(--text-primary)',
                cursor: readOnly ? 'not-allowed' : 'pointer',
                opacity: readOnly ? 0.6 : 1,
              }}
            >
              <div className="text-sm font-medium" style={{ color: checked ? 'var(--accent-primary)' : 'var(--text-primary)' }}>
                {checked && <span className="mr-1">✓</span>}{opt.label}
              </div>
              <div className="text-[11px] text-muted mt-0.5">{opt.desc}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

// 单选分段按钮 — 选项固定枚举,只能选一个(再点同一项可取消回空)。
// 带 ✨AI 判断 小标 + 动态提示:已选时说明当前判定可改,未选时说明它影响扩展词方向。
function SegmentedRow({
  label, options, value, onChange, readOnly, aiBadge = false,
}: {
  label: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  readOnly: boolean;
  aiBadge?: boolean;
}) {
  const current = options.find(o => o.value === value);
  const hint = current
    ? `已按资料自动判为「${current.label}」,不对可直接改`
    : '按资料自动判断;影响扩展词方向(服务工具→功能/价格/集成 · 制造商→厂家/参数/OEM)';
  return (
    <div>
      <div className="flex items-center gap-2 mb-1">
        <label className="block text-xs text-secondary">{label}</label>
        {aiBadge && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                style={{ background: 'rgba(139,92,246,0.15)', color: '#8b5cf6' }}>
            ✨AI 判断
          </span>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {options.map(opt => {
          const active = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              disabled={readOnly}
              onClick={() => onChange(active ? '' : opt.value)}
              className="px-3 py-1.5 rounded-md text-sm border"
              style={{
                background: active ? 'var(--accent-primary)' : 'var(--bg-card)',
                borderColor: active ? 'var(--accent-primary)' : 'var(--border-color)',
                color: active ? '#fff' : 'var(--text-primary)',
                fontWeight: active ? 600 : 400,
                cursor: readOnly ? 'not-allowed' : 'pointer',
                opacity: readOnly ? 0.6 : 1,
              }}
            >
              {active && <span className="mr-1">●</span>}{opt.label}
            </button>
          );
        })}
      </div>
      <span className="block mt-1 text-xs text-muted">{hint}</span>
    </div>
  );
}

function TagsRow({ label, required, readOnly, value, onChange, placeholder }: TagsProps) {
  const [draft, setDraft] = useState('');
  const add = () => {
    const v = draft.trim();
    if (!v) return;
    if (value.includes(v)) { setDraft(''); return; }
    onChange([...value, v]);
    setDraft('');
  };
  const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i));
  return (
    <div>
      <Label text={label} required={required} />
      <div className="flex flex-wrap gap-1.5 mb-2">
        {value.map((tag, i) => (
          <span key={`${tag}-${i}`}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs"
                style={{ background: 'var(--bg-tertiary)', color: 'var(--accent-primary)' }}>
            {tag}
            {!readOnly && (
              <button type="button" onClick={() => remove(i)} className="text-muted hover:text-primary">×</button>
            )}
          </span>
        ))}
      </div>
      {!readOnly && (
        <div className="flex gap-2">
          <input type="text" value={draft}
                 onChange={e => setDraft(e.target.value)}
                 onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add(); } }}
                 placeholder={placeholder || '输入后回车添加'}
                 className="flex-1 text-sm px-3 py-1.5 rounded-md"
                 style={{ background: 'var(--bg-input)', color: 'var(--text-primary)',
                          border: '1px solid var(--border-color)' }} />
          <button type="button" onClick={add}
                  className="text-xs px-3 py-1.5 rounded-md"
                  style={{ background: 'var(--accent-primary)', color: '#fff' }}>添加</button>
        </div>
      )}
    </div>
  );
}
