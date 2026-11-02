// Shapes mirror backend/app/models/advanced.py. When the backend schema
// changes, update this file in lockstep.

import type { CISourceTrace, CISourcePreference } from './sourceAnalysis';
export type { CISourceTrace, CISourcePreference } from './sourceAnalysis';

export type AdvancedMode =
  | 'aeo'
  | 'compare'
  | 'crawlTest'
  | 'authority'
  | 'citation'
  | 'visibility'
  | 'entity';

// ---- Requests ----

export interface CompareRequest {
  urls: string[];
}

export interface SingleUrlRequest {
  url: string;
}

export interface AiVisibilityRequest {
  url: string;
  custom_queries?: string[];
}

export interface EntityAuditRequest {
  entity_name: string;
  entity_type: 'brand' | 'product' | 'person';
}

export type AdvancedRequestBody<M extends AdvancedMode> = M extends 'compare'
  ? CompareRequest
  : M extends 'aeo'
  ? SingleUrlRequest
  : M extends 'visibility'
  ? AiVisibilityRequest
  : M extends 'entity'
  ? EntityAuditRequest
  : SingleUrlRequest;

// ---- Responses ----

export interface CompareUrlResult {
  url: string;
  domain: string;
  score: number;
  grade: string;
  categories: Record<string, { earned: number; max: number }>;
}

export interface CompareAdvantage {
  category: string;
  ranked: Array<{ domain: string; percent: number }>;
}

export interface CompareResponse {
  urls: string[];
  results: CompareUrlResult[];
  categories: string[];
  advantages: CompareAdvantage[];
  winner?: { domain: string; score: number; grade: string; lead: number } | null;
}

export interface CrawlTestResponse {
  url: string;
  domain: string;
  robots: {
    found: boolean;
    bots: Array<{ bot: string; ua: string; status: string }>;
    blocked: string[];
  };
  waf: {
    baseline_status: number | null;
    baseline_size: number;
    bots: Array<{
      bot: string;
      status_code: number | null;
      size: number;
      result: string;
      error: string | null;
    }>;
    blocked: string[];
  };
  common_crawl: {
    found: boolean;
    count: number;
    samples: string[];
    status: number | null;
    error: string | null;
  };
  total_issues: number;
}

export interface AuthorityAuditResponse {
  url: string;
  domain: string;
  brand: string;
  score: number;
  max_score: number;
  percent: number;
  grade: string;
  reviews: { platforms: string[]; has_schema: boolean };
  awards: {
    keywords: string[];
    has_schema: boolean;
    badges: string[];
    signal_count: number;
  };
  google: {
    indexed_pages: number | null;
    kg_schema_fields: number;
    wikipedia_or_wikidata: boolean;
    score: number;
  };
  mentions: { platforms: string[] };
}

export interface CitationCheckResponse {
  url: string;
  domain: string;
  brand: string;
  engine: string;
  total_queries: number;
  valid_queries: number;
  cited_queries: number;
  citation_rate: number;
  total_citations: number;
  grade: string;
  queries: Array<{
    query: string;
    cited: boolean;
    citations: string[];
    mentioned?: boolean;
    total_sources?: number;
    error: boolean;
  }>;
}

export interface AiVisibilityResponse {
  url: string;
  domain: string;
  brand: string;
  engines: string[];
  scores: {
    visibility: number;
    entity: number;
    competitor: number;
    stability: number;
    content_gap: number;
  };
  total_score: number;
  max_score: number;
  grade: string;
  grade_label: string;
  per_engine_rates: Record<string, number>;
  top_competitors: Array<{ domain: string; mentions: number }>;
  framings: Record<string, number>;
  content_gaps: string[];
  query_count: number;
  stability_runs: number;
  source_trace?: CISourceTrace;
  source_preference?: CISourcePreference;
}

export interface EntityAuditResponse {
  entity: string;
  entity_type: string;
  scores: Record<string, number>;
  total_score: number;
  max_score: number;
  percent: number;
  grade: string;
  engines_used?: string[];
  knowledge_graph: {
    wikipedia: boolean;
    wikidata: boolean;
    wikidata_id: string | null;
    google_kg: boolean;
    baidu_baike: boolean;
    platforms_found: string[];
  };
  platforms: { found: string[]; not_found: string[] };
  sentiment: string;
  best_framing: string;
  per_engine?: Record<string, { sentiment: string; framing: string; recognized: boolean }>;
  content_gaps: string[];
  recognition_rate: number;
  stability_runs: number;
  total_runs_per_query?: number;
  source_trace?: CISourceTrace;
  source_preference?: CISourcePreference;
}

export interface AeoVisibilityResponse {
  url: string;
  domain: string;
  score: number;
  grade: string;
  max_score: number;
  categories: Record<string, { earned: number; max: number }>;
  page_results: Array<{
    path: string;
    score: number;
    weakest_signal: string;
    weakest_detail: string;
  }>;
  priority_improvements: Array<{
    category: string;
    percent: number;
  }>;
}

export type AdvancedResponseOf<M extends AdvancedMode> = M extends 'compare'
  ? CompareResponse
  : M extends 'aeo'
  ? AeoVisibilityResponse
  : M extends 'crawlTest'
  ? CrawlTestResponse
  : M extends 'authority'
  ? AuthorityAuditResponse
  : M extends 'citation'
  ? CitationCheckResponse
  : M extends 'visibility'
  ? AiVisibilityResponse
  : M extends 'entity'
  ? EntityAuditResponse
  : never;
