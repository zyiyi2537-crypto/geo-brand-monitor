import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

type Lng = 'en' | 'zh';
type Ns = 'main' | 'result' | 'knowledge';

// Tracks which (lng, ns) packs have been addResourceBundle'd, keyed as
// "lng:ns" so one user's session never re-fetches the same chunk.
const loaded = new Set<string>();

function detectInitialLng(): Lng {
  try {
    const stored = localStorage.getItem('i18nextLng');
    if (stored === 'en' || stored === 'zh') return stored;
  } catch {
    // Private-mode browsers / SSR shims can throw on localStorage access
  }
  const nav =
    typeof navigator !== 'undefined' ? (navigator.language || 'en').toLowerCase() : 'en';
  return nav.startsWith('zh') ? 'zh' : 'en';
}

async function loadPack(ns: Ns, lng: Lng): Promise<void> {
  const key = `${lng}:${ns}`;
  if (loaded.has(key)) return;
  let m: { default: Record<string, unknown> };
  if (ns === 'main') {
    m = await (lng === 'zh' ? import('./zh') : import('./en'));
  } else if (ns === 'result') {
    m = await (lng === 'zh' ? import('./zh-result') : import('./en-result'));
  } else {
    m = await (lng === 'zh' ? import('./zh-knowledge') : import('./en-knowledge'));
  }
  i18n.addResourceBundle(lng, 'translation', m.default, true, true);
  loaded.add(key);
}

function loadedNsFor(lng: Lng): Ns[] {
  return (['main', 'result', 'knowledge'] as Ns[]).filter((ns) =>
    loaded.has(`${lng}:${ns}`),
  );
}

/**
 * Bootstrap hook called from main.tsx BEFORE createRoot.render. Awaits the
 * initial language's main pack so the first React render never shows raw
 * translation keys. Safe to call twice — re-entry is a no-op.
 */
export async function initI18n(): Promise<void> {
  if (i18n.isInitialized) return;
  const initialLng = detectInitialLng();
  // Kick off the chunk fetch in parallel with i18n.init so the two I/O waits
  // overlap instead of running back-to-back.
  const packPromise = loadPack('main', initialLng);
  await i18n.use(initReactI18next).init({
    resources: {},
    lng: initialLng,
    supportedLngs: ['en', 'zh'],
    // Key parity is 100% across en/zh (verified: main 1282/1282, result
    // 548/548, knowledge 135/135). Disabling fallback means we never need
    // to ship the "other" language upfront just in case a key is missing.
    fallbackLng: false,
    defaultNS: 'translation',
    load: 'languageOnly',
    // Tells i18next "I know resources: {} is empty — I'll addResourceBundle
    // later, don't look for a backend plugin." Required when using dynamic
    // imports to fill bundles.
    partialBundledLanguages: true,
    // Keep Suspense ON (default). main.tsx awaits initI18n before render
    // so resources are attached by first paint; Suspense then guards the
    // narrow race window inside i18next's init lifecycle that would
    // otherwise flash raw keys.
    interpolation: { escapeValue: false },
  });
  await packPromise;
  try {
    localStorage.setItem('i18nextLng', initialLng);
  } catch {
    /* noop */
  }
}

/**
 * Lazy-load a route-level namespace pack (`result` / `knowledge`) for the
 * CURRENT language only. Callers (useLoadNs) are unchanged — the signature
 * is the same as before, but the implementation only fetches one language
 * instead of both.
 */
export async function loadNamespace(ns: 'result' | 'knowledge'): Promise<void> {
  const lng = (i18n.language as Lng) || 'en';
  await loadPack(ns, lng);
}

/**
 * Flip UI language. Before changing, download target-language packs for every
 * namespace the current session has already loaded — otherwise the user would
 * briefly see raw translation keys for any page they've already visited.
 * Caller should await this (LanguageSwitcher does).
 */
export async function switchLanguage(targetLng: Lng): Promise<void> {
  if ((i18n.language as Lng) === targetLng) return;
  const currentLng = (i18n.language as Lng) || 'en';
  for (const ns of loadedNsFor(currentLng)) {
    await loadPack(ns, targetLng);
  }
  await i18n.changeLanguage(targetLng);
  try {
    localStorage.setItem('i18nextLng', targetLng);
  } catch {
    /* noop */
  }
}

export default i18n;
