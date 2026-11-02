/** Shared source analysis types used by CompetitiveIntel, AI Visibility, and Entity audit. */

export interface CISourceArticle {
  url: string;
  title: string;
  citations: number;
}

export interface CISourceEntry {
  platform: string;
  article_count: number;
  total_citations: number;
  engines: string[];
  queries: string[];
  source_type: string;
  articles: CISourceArticle[];
}

export interface CISelfCitation {
  url: string;
  engine: string;
  query: string;
  title: string;
}

export interface CISourceTrace {
  sources: CISourceEntry[];
  self_citations: CISelfCitation[];
  missing_queries: string[];
  total_sources: number;
  total_citations: number;
}

export interface CIEnginePreference {
  engine: string;
  total_citations: number;
  type_distribution: Record<string, number>;
  top_domains: Array<{ domain: string; count: number }>;
}

export interface CISourcePreference {
  per_engine: CIEnginePreference[];
  overall_distribution: Record<string, number>;
  engine_totals: Record<string, number>;
  recommendations: Array<{ engine: string; type: string; message: string }>;
  stats: { total_sources: number; total_citations: number; avg_citations: number };
}
