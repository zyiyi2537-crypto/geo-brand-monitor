// Advanced modes surfaced in the Result-page rerun dropdown.
// Each entry maps to a geo_checker CLI sub-mode; route target is /advanced/{key}.
// `minTier` must stay in sync with backend/geo/models/advanced.py MODE_MIN_TIER.
export type AdvancedMode = 'aeo' | 'compare' | 'crawlTest' | 'authority' | 'citation' | 'visibility' | 'entity';

export type RerunMode = 'default' | AdvancedMode;

export const ADVANCED_MODES: { key: AdvancedMode; minTier: 'free' | 'pro' | 'starter' }[] = [
  { key: 'aeo', minTier: 'free' },
  { key: 'visibility', minTier: 'pro' },
  { key: 'compare', minTier: 'pro' },
  { key: 'crawlTest', minTier: 'pro' },
  { key: 'authority', minTier: 'pro' },
  { key: 'citation', minTier: 'pro' },
  { key: 'entity', minTier: 'free' },
];
