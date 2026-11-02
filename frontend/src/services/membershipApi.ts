import { readApiError, localizedHeaders } from './apiError';

// Define types locally to avoid import issues
export type TierType = 'saas' | 'service';

export interface Membership {
  id: number;
  slug: string;
  name: string;
  price: number;
  currency: string;
  period: string;
  description: string;
  popular: boolean;
  features: string[];
  not_included: string[];
  tier_type: TierType;
  monthly_check_quota: number; // 0 = unlimited
  allowed_check_categories: string[] | null; // null = all 25
  features_json: Record<string, any> | null;
  display_order: number;
  created_at: string;
  updated_at: string;
}

export interface UserMembership {
  id: number;
  user_id: number;
  membership_id: number;
  start_date: string;
  end_date: string;
  is_active: boolean;
}

export interface UsageResponse {
  quota: number;       // 0 = unlimited
  used: number;
  remaining: number;   // -1 = unlimited
  year_month: string;
}

export interface ContactSalesPayload {
  name: string;
  email: string;
  website?: string;
  tier_slug?: string;
  message?: string;
}

const CURRENCY_SYMBOLS: Record<string, string> = {
  cny: '¥',
  usd: '$',
  eur: '€',
  gbp: '£',
  jpy: '¥',
  hkd: 'HK$',
};

/** Best-effort symbol lookup; falls back to upper-cased ISO code + space. */
export function currencySymbol(currency: string | undefined): string {
  if (!currency) return '';
  const key = currency.toLowerCase();
  return CURRENCY_SYMBOLS[key] ?? `${currency.toUpperCase()} `;
}

/**
 * Render a tier price with the right currency symbol.
 *
 * - SaaS tiers: read `tier.currency` (e.g. ¥19.9 for pro, ¥0 for free).
 * - Service tiers: prefer the human-curated `price_range_usd` from
 *   `features_json` if present; otherwise fall back to "$<rounded>+".
 */
export function formatTierPrice(tier: Membership): string {
  if (tier.tier_type === 'service') {
    const range = (tier.features_json as Record<string, unknown> | null)?.price_range_usd;
    if (typeof range === 'string' && range.length > 0) return range;
    return `$${Math.round(tier.price).toLocaleString()}+`;
  }
  // Use thousand separators for whole-dollar prices (e.g. 2500 → "2,500"),
  // but preserve decimals for fractional prices (e.g. 9.99).
  const priceStr = Number.isInteger(tier.price)
    ? tier.price.toLocaleString('en-US')
    : String(tier.price);
  return `${currencySymbol(tier.currency)}${priceStr}`;
}

/**
 * Error thrown by membershipApi calls. Preserves HTTP status so callers
 * (notably useMembership) can distinguish an expired token (401) from a
 * generic network/parse failure.
 */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

class MembershipApi {
  private baseUrl: string;

  constructor() {
    this.baseUrl = '/api';
  }

  async getMemberships(): Promise<Membership[]> {
    const response = await fetch(`${this.baseUrl}/memberships`, {
      headers: localizedHeaders(),
    });
    if (!response.ok) {
      throw new Error(await readApiError(response, 'Failed to get memberships'));
    }
    return response.json();
  }

  async getUserMembership(token: string): Promise<UserMembership> {
    const response = await fetch(`${this.baseUrl}/user-membership`, {
      headers: localizedHeaders({ Authorization: `Bearer ${token}` }),
    });
    if (!response.ok) {
      throw new ApiError(
        response.status,
        await readApiError(response, 'Failed to get user membership'),
      );
    }
    return response.json();
  }

  async cancelMembership(token: string): Promise<{ message: string }> {
    const response = await fetch(`${this.baseUrl}/cancel-membership`, {
      method: 'POST',
      headers: localizedHeaders({ Authorization: `Bearer ${token}` }),
    });
    if (!response.ok) {
      throw new Error(await readApiError(response, 'Failed to cancel membership'));
    }
    return response.json();
  }

  async getUsage(token: string): Promise<UsageResponse> {
    const response = await fetch(`${this.baseUrl}/users/me/usage`, {
      headers: localizedHeaders({ Authorization: `Bearer ${token}` }),
    });
    if (!response.ok) {
      throw new Error(await readApiError(response, 'Failed to get usage'));
    }
    return response.json();
  }

  async submitContactForm(payload: ContactSalesPayload): Promise<{ message: string; lead_id: number }> {
    const response = await fetch(`${this.baseUrl}/contact-sales`, {
      method: 'POST',
      headers: localizedHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(await readApiError(response, 'Failed to submit contact form'));
    }
    return response.json();
  }

}

export const membershipApi = new MembershipApi();
