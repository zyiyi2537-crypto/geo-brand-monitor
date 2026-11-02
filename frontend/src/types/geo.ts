export interface CheckResult {
  category: string;
  status: string; // PASS, WARN, FAIL, INFO
  message: string;
  fix?: string;
  /** i18n key path under result.checks.* when the check was emitted
   *  via geo_checker.emit_check(). Absent for un-migrated legacy checks. */
  message_key?: string | null;
  /** Interpolation params for message_key (e.g. {count: 12, url: "..."}). */
  message_params?: Record<string, unknown> | null;
  /** i18n key under result.fixes.* for the fix recommendation. Absent for
   *  legacy fix() calls that haven't been migrated to emit_fix(). */
  fix_key?: string | null;
  /** Interpolation params for fix_key. */
  fix_params?: Record<string, unknown> | null;
}

export interface GeoTestRequest {
  url: string;
  include_fix: boolean;
}

export interface GeoTestResult {
  url: string;
  score: number;
  grade: string;
  checks: CheckResult[];
  summary: {
    pass_count: number;
    warn_count: number;
    fail_count: number;
    info_count: number;
    total_checks: number;
  };
  /** Membership slug under which this check ran ('free' | 'pro' | 'starter' | 'growth' | 'scale'). */
  tier?: string | null;
  /** Category labels that were NOT executed for this tier. Empty for unlocked tiers. */
  locked_categories?: string[] | null;
}
