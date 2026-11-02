import type { ReactElement } from 'react';
import type { CheckResult } from '../../types/geo';
import { RobotsBotMatrix } from './visuals/RobotsBotMatrix';
import { MetaTagsGrid } from './visuals/MetaTagsGrid';
import { PlatformGrid } from './visuals/PlatformGrid';

/**
 * resolveCategoryVisual — plain function that returns a React element for
 * the rich visualization of a given category, or `null` when there is no
 * visual available.
 *
 * **Why not a component?** If this were a component and the caller did
 * `const v = <CategoryVisual .../>`, the variable `v` would be a truthy
 * React element OBJECT even when the component internally returns null.
 * That broke the `{v ? v : <list fallback/>}` ternary — the fallback
 * never rendered, so categories without a visual (HTTPS, sitemap.xml,
 * Mobile & Weight, and every stub) silently showed up as empty blocks.
 *
 * Returning null from a plain function propagates cleanly: callers can
 * write `resolveCategoryVisual(...) ?? <listFallback/>` and get the
 * intended fallback behaviour.
 *
 * Each sub-component still parses `checks[].message` defensively. If the
 * parser returns null (unexpected message shape), the sub-component
 * returns null itself — so we also return null here, and the list
 * fallback takes over.
 *
 * Stubs for the other 6 high-value categories are wired up but return
 * null for now — they'll be filled in a follow-up pass.
 */
export function resolveCategoryVisual(
  category: string,
  checks: CheckResult[],
): ReactElement | null {
  if (!checks || checks.length === 0) return null;

  switch (category) {
    case 'robots.txt':
      return <RobotsBotMatrix checks={checks} />;

    case 'Meta Tags':
      return <MetaTagsGrid checks={checks} />;

    case 'Cross-Platform Content Distribution':
      return <PlatformGrid checks={checks} variant="cross-platform" />;

    case 'Social Signals':
      // Re-uses the same visual — same underlying data shape (platform hits).
      return <PlatformGrid checks={checks} variant="social" />;

    // Stubs — currently return null, so list fallback renders.
    // case 'HTTPS':
    // case 'sitemap.xml':
    // case 'Mobile-Friendliness & Page Weight':
    // case 'Schema Breadcrumbs & Knowledge Panel':
    // case 'AI Crawl Readiness':
    // case 'Structured Data':

    default:
      return null;
  }
}
