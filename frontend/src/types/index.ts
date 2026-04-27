// ============================================================
// DCE Platform — TypeScript Entity Interfaces
// ============================================================

// ─── Auth / User ────────────────────────────────────────────

export interface User {
  id: string;
  phone: string;
  full_name: string | null;
  email: string | null;
  is_kyc_verified: boolean;
  kyc_level: 'NONE' | 'BASIC' | 'FULL';
  referral_code: string;
  date_joined: string;
  last_login: string | null;
}

export interface AuthTokens {
  access: string;
  refresh: string;
}

export interface OTPSendRequest {
  phone: string;
  purpose?: 'LOGIN' | 'REGISTER' | 'PASSWORD_RESET';
}

export interface OTPVerifyRequest {
  phone: string;
  otp: string;
  purpose?: 'LOGIN' | 'REGISTER' | 'PASSWORD_RESET';
}

export interface AuthResponse {
  user: User;
  tokens: AuthTokens;
  is_new_user: boolean;
}

// ─── Wallet ──────────────────────────────────────────────────

export type WalletTier = 'BRONZE' | 'SILVER' | 'GOLD' | 'PLATINUM';

export interface Wallet {
  id: string;
  balance_bdt: string;
  credits: number;
  tier: WalletTier;
  is_frozen: boolean;
  freeze_reason: string | null;
  monthly_deposit_total: string;
  monthly_withdrawal_total: string;
}

export type TransactionType =
  | 'DEPOSIT'
  | 'WITHDRAWAL'
  | 'TRANSFER'
  | 'AI_USAGE'
  | 'SUBSCRIPTION'
  | 'PURCHASE'
  | 'REFUND'
  | 'BONUS'
  | 'REFERRAL';

export type TransactionStatus = 'PENDING' | 'COMPLETED' | 'FAILED' | 'REVERSED';

export interface Transaction {
  id: string;
  transaction_id: string;
  transaction_type: TransactionType;
  amount: string;
  currency: 'BDT' | 'CREDITS';
  status: TransactionStatus;
  description: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export type DepositMethod = 'BKASH' | 'NAGAD' | 'SSLCOMMERZ';

export interface DepositRequest {
  id: string;
  method: DepositMethod;
  amount_bdt: string;
  status: 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'EXPIRED' | 'FAILED';
  payment_url: string | null;
  expires_at: string;
  created_at: string;
}

export interface WithdrawalRequest {
  id: string;
  method: DepositMethod;
  amount_bdt: string;
  account_number: string;
  status: 'PENDING' | 'APPROVED' | 'PROCESSING' | 'COMPLETED' | 'REJECTED';
  created_at: string;
}

// ─── AI Gateway ──────────────────────────────────────────────

export type AIProvider = 'OPENAI' | 'CLAUDE' | 'DEEPSEEK' | 'GEMINI' | 'COHERE';

export interface AIService {
  id: string;
  name: string;
  slug: string;
  provider: AIProvider;
  model_id: string;
  description: string;
  capabilities: string[];
  sell_price_credits: number;
  cost_per_request_bdt: string;
  max_tokens: number;
  is_active: boolean;
}

export interface AIConversation {
  id: string;
  service: string;
  title: string | null;
  total_cost_credits: number;
  created_at: string;
  updated_at: string;
}

export type MessageRole = 'USER' | 'ASSISTANT' | 'SYSTEM';

export interface AIMessage {
  id: string;
  role: MessageRole;
  content: string;
  tokens_used: number | null;
  created_at: string;
}

export interface AIChatRequest {
  service_slug: string;
  message: string;
  conversation_id?: string;
  stream?: boolean;
}

export interface AIChatResponse {
  conversation_id: string;
  message: string;
  tokens_used: number;
  credits_deducted: number;
  remaining_credits: number;
}

// ─── Streaming ───────────────────────────────────────────────

export type ContentType = 'MOVIE' | 'SERIES' | 'COURSE' | 'DOCUMENTARY' | 'SHORT';
export type ContentStatus = 'DRAFT' | 'PUBLISHED' | 'ARCHIVED';

export interface StreamingCategory {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  content_count: number;
}

export interface ContentItem {
  id: string;
  title: string;
  slug: string;
  content_type: ContentType;
  description: string;
  thumbnail_url: string | null;
  release_year: number | null;
  duration_minutes: number | null;
  categories: StreamingCategory[];
  cast: string[];
  director: string | null;
  language: string;
  subtitle_languages: string[];
  rating: string | null;
  is_featured: boolean;
  is_free: boolean;
  required_plan: string | null;
  status: ContentStatus;
  created_at: string;
}

export interface ContentEpisode {
  id: string;
  season_number: number;
  episode_number: number;
  title: string;
  description: string | null;
  duration_minutes: number | null;
  thumbnail_url: string | null;
}

export interface WatchProgress {
  content: string;
  episode: string | null;
  progress_seconds: number;
  duration_seconds: number;
  completed: boolean;
  last_watched_at: string;
}

// ─── Subscriptions ───────────────────────────────────────────

export type PlanType = 'STARTER' | 'GROWTH' | 'PRO';
export type BillingCycle = 'MONTHLY' | 'QUARTERLY' | 'YEARLY';
export type SubscriptionStatus = 'ACTIVE' | 'CANCELLED' | 'EXPIRED' | 'PAUSED' | 'TRIAL';

export interface SubscriptionPlan {
  id: string;
  name: string;
  slug: string;
  plan_type: PlanType;
  billing_cycle: BillingCycle;
  price_bdt: string;
  monthly_credits: number;
  ai_requests_per_day: number;
  streaming_quality: 'SD' | 'HD' | 'FHD' | '4K';
  concurrent_streams: number;
  has_ai_access: boolean;
  has_streaming: boolean;
  has_marketplace: boolean;
  features: string[];
  is_popular: boolean;
}

export interface UserSubscription {
  id: string;
  plan: SubscriptionPlan;
  status: SubscriptionStatus;
  start_date: string;
  end_date: string;
  auto_renew: boolean;
  cancelled_at: string | null;
  trial_end_date: string | null;
}

// ─── Marketplace ─────────────────────────────────────────────

export type ProductCategory = 'SAAS' | 'AI_TOOL' | 'DIGITAL_ASSET' | 'COURSE' | 'BUNDLE';

export interface MarketplaceProduct {
  id: string;
  name: string;
  slug: string;
  description: string;
  long_description: string | null;
  category: ProductCategory;
  thumbnail_url: string | null;
  price_bdt: string;
  price_credits: number | null;
  vendor_name: string;
  rating: string | null;
  review_count: number;
  is_featured: boolean;
  features: string[];
  tags: string[];
}

export interface Order {
  id: string;
  order_number: string;
  product: MarketplaceProduct;
  quantity: number;
  unit_price: string;
  total_price: string;
  payment_method: 'WALLET_BDT' | 'WALLET_CREDITS';
  status: 'PENDING' | 'COMPLETED' | 'REFUNDED' | 'CANCELLED';
  created_at: string;
}

// ─── Notifications ────────────────────────────────────────────

export type NotificationType =
  | 'SYSTEM'
  | 'PAYMENT'
  | 'AI_USAGE'
  | 'SUBSCRIPTION'
  | 'PROMOTION'
  | 'SECURITY';

export interface Notification {
  id: string;
  notification_type: NotificationType;
  title: string;
  message: string;
  is_read: boolean;
  action_url: string | null;
  created_at: string;
}

// ─── API Responses ────────────────────────────────────────────

export interface APISuccess<T> {
  status: 'success';
  data: T;
  message?: string;
}

export interface APIError {
  status: 'error';
  message: string;
  errors?: Record<string, string[]>;
  code?: string;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// ─── UI State ─────────────────────────────────────────────────

export interface LoadingState {
  isLoading: boolean;
  error: string | null;
}

export interface SelectOption {
  value: string;
  label: string;
}
