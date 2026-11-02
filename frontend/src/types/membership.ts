export interface Membership {
  id: number;
  name: string;
  price: number;
  period: string;
  description: string;
  popular: boolean;
  features: string[];
  not_included: string[];
  created_at: string;
  updated_at: string;
}