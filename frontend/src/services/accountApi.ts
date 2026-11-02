import type { GeoTestResult } from '../types/geo';
import { ApiError } from './membershipApi';
import { readApiError, localizedHeaders } from './apiError';

export interface DetectionRecordSummary {
  id: number;
  url: string;
  score: number | null;
  grade: string | null;
  tier: string | null;
  mode: string;
  created_at: string;
  deleted_at: string | null;
}

export interface DetectionRecordDetail extends DetectionRecordSummary {
  result: GeoTestResult;
}

export interface DetectionRecordList {
  items: DetectionRecordSummary[];
  total: number;
  page: number;
  size: number;
}

export interface PaymentRecord {
  id: number;
  membership_slug: string;
  provider: string;
  checkout_url: string | null;
  amount_cents: number;
  currency: string;
  status: string;
  created_at: string;
  completed_at: string | null;
}

export interface PaymentRecordList {
  items: PaymentRecord[];
  total: number;
  page: number;
  size: number;
}

class AccountApi {
  private baseUrl: string;

  constructor() {
    this.baseUrl = '/api/account';
  }

  async listDetections(token: string, page = 1, size = 10): Promise<DetectionRecordList> {
    const response = await fetch(
      `${this.baseUrl}/detections?page=${page}&size=${size}`,
      { headers: localizedHeaders({ Authorization: `Bearer ${token}` }) },
    );
    if (!response.ok) {
      throw new ApiError(response.status, await readApiError(response, 'Failed to load history'));
    }
    return response.json();
  }

  async getDetection(token: string, id: number): Promise<DetectionRecordDetail> {
    const response = await fetch(`${this.baseUrl}/detections/${id}`, {
      headers: localizedHeaders({ Authorization: `Bearer ${token}` }),
    });
    if (!response.ok) {
      throw new ApiError(response.status, await readApiError(response, 'Failed to load record'));
    }
    return response.json();
  }

  async deleteDetection(token: string, id: number): Promise<void> {
    const response = await fetch(`${this.baseUrl}/detections/${id}`, {
      method: 'DELETE',
      headers: localizedHeaders({ Authorization: `Bearer ${token}` }),
    });
    if (!response.ok) {
      throw new ApiError(response.status, await readApiError(response, 'Failed to delete record'));
    }
  }

  async listPayments(token: string, page = 1, size = 10): Promise<PaymentRecordList> {
    const response = await fetch(
      `${this.baseUrl}/payments?page=${page}&size=${size}`,
      { headers: localizedHeaders({ Authorization: `Bearer ${token}` }) },
    );
    if (!response.ok) {
      throw new ApiError(response.status, await readApiError(response, 'Failed to load payments'));
    }
    return response.json();
  }

  async changePassword(token: string, oldPassword: string, newPassword: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/change-password`, {
      method: 'POST',
      headers: localizedHeaders({
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      }),
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    });
    if (!response.ok) {
      throw new ApiError(response.status, await readApiError(response, 'Failed to change password'));
    }
  }
}

export const accountApi = new AccountApi();
