// Shapes of the API responses the screens use. Many endpoints return plain
// dicts, so these are written by hand to match platform/app/services/*.

export interface Me {
  id: string;
  email: string;
  username: string | null;
  display_name: string | null;
  phone: string | null;
  kyc_tier: number;
  is_admin: boolean;
  terms_accepted: boolean;
  excluded_until: string | null;
  reality_check_minutes: number | null;
}

export interface Tier {
  id: number;
  name: string;
  price_label: string;
  buy_in_cents: number;
  fee_cents: number;
  total_cents: number;
  total_kes_reference: number;
  seats: number;
  min_players: number;
  payout_bps: number[];
  max_prize_pool_cents: number;
}

export interface Seat {
  username: string;
  start_vote?: boolean;
  status: "registered" | "playing" | "finished";
  ready: boolean;
  finish_position: number | null;
  prize_cents: number | null;
}

export type TableStatus = "open" | "ready_check" | "running" | "finished" | "cancelled";

export interface TableView {
  id: string;
  status: TableStatus;
  name: string;
  title: string | null;
  message: string | null;
  price_label: string;
  buy_in_cents: number;
  seats_total: number;
  min_players: number;
  players: number;
  prize_pool_cents: number;
  payout_bps: number[];
  start_mode: "when_full" | "scheduled" | "practice";
  bots: number;
  is_private: boolean;
  is_organizer: boolean;
  invite_code: string | null;
  scheduled_start_at: string | null;
  ready_deadline: string | null;
  seats: Seat[];
  me: (Seat & { can_pull_out: boolean; pull_out_seconds_left: number; alone?: boolean }) | null;
}

export interface LobbyTable {
  id: string;
  name: string;
  title: string | null;
  organizer: string | null;
  price_label: string;
  status: TableStatus;
  players: number;
  seats_total: number;
  scheduled_start_at: string | null;
}

export interface Wallet {
  available_usd_cents: number;
  kes_reference: number;
  usd_kes_rate: string;
  real_money_enabled: boolean;
}

export interface HistoryItem {
  transaction_id: number;
  kind: string;
  amount_usd_cents: number;
  memo: string | null;
  at: string;
}

export interface Deposit {
  reference: string;
  status: "pending" | "success" | "failed" | "abandoned" | "expired" | "mismatch";
  channel: "card" | "mpesa";
  credit_usd_cents: number;
  charge_currency: string;
  charge_amount: number;
}

export interface Withdrawal {
  reference: string;
  status: string;
  amount_usd_cents: number;
  fee_usd_cents: number;
  payout_amount: number;
  review_reasons: string | null;
  created_at: string;
}

export interface FriendItem {
  user_id: string;
  username: string | null;
  name: string;
  request_id?: string;
}

export interface TablePreview {
  table_id: string;
  title: string;
  message: string | null;
  organizer: string | null;
  organizer_ref: string | null;
  price_label: string;
  seats_total: number;
  players: number;
  status: TableStatus;
  scheduled_start_at: string | null;
  is_private: boolean;
}

export interface Invite {
  invite_id: string;
  from: string;
  message: string | null;
  expires_at: string;
  table: TablePreview;
}
