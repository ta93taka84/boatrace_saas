export type Lane = 1 | 2 | 3 | 4 | 5 | 6;

export interface Racer {
  lane: number;
  racer_id: string;
  name: string;
  class: string;
  branch: string;
  age: number;
  weight: number;
  f_count: number;
  l_count: number;
  avg_st: number;
  win_rate_all: number;
  in2_rate_all: number;
  in3_rate_all: number;
  win_rate_venue: number;
  in2_rate_venue: number;
  in3_rate_venue: number;
  motor_no: number;
  motor_in2_rate: number;
  motor_in3_rate: number;
  boat_no: number;
  boat_in2_rate: number;
  boat_in3_rate: number;
  exhibit_time?: number | null;
  tilt?: number | null;
  /** スタート展示の進入コース。枠番と違えば前づけがあったということ。 */
  ex_course?: number | null;
  /** スタート展示のST。フライングは負の値。 */
  ex_st?: number | null;
  propeller_new?: boolean | null;
  parts?: string[] | null;
  /** 今節の前走。節の初日は空。 */
  prev_race_no?: number | null;
  prev_course?: number | null;
  /** 前走のST。フライングは負の値。 */
  prev_st?: number | null;
  prev_rank?: number | null;
  /** 着順が数字でないときの記号（F=フライング、L=出遅れ など）。 */
  prev_foul?: string | null;
}

export interface Conditions {
  weather: string | null;
  temperature: number | null;
  water_temp: number | null;
  wind_speed: number | null;
  wind_dir_code: number | null;
  wave_height: number | null;
}

export interface RaceResult {
  winner_lane: number | null;
  finish: Record<string, number>;
  kimarite: string | null;
  payouts: Record<string, { combo: string; payout: number; popularity: number | null }>;
}

export interface Race {
  race_no: number;
  closes_at?: string;
  racers?: Racer[];
  conditions?: Conditions;
  market_prob?: Record<string, number>;
  overround?: number;
  /** 表示中のオッズを取得した時刻（HH:MM）。オッズは締切に向けて動くため鮮度が要る。 */
  odds_at?: string;
  /** モデル単独の推定。記録用で、画面に出すのは pub_prob のほう。 */
  model_prob?: Record<string, number>;
  /** 公開する確率。model_prob を市場オッズへ blend_weight ぶん引き戻したもの。 */
  pub_prob?: Record<string, number>;
  /** 市場へどれだけ引き戻したか。0で市場そのまま、1でモデル単独。 */
  blend_weight?: number;
  /**
   * 前日に出した暫定予測か。翌日ぶんは三連単オッズが公開されていないため、
   * 市場へ引き戻せず、展示タイムも気象も無い。期待値と買い目は出さない。
   */
  provisional?: boolean;
  ev?: Record<string, number>;
  top_lane?: number;
  top_ev?: number;
  /** 推奨買い目。EVの高い順。オッズが取れていないレースでは付かない。 */
  picks?: TrifectaPick[];
  result?: RaceResult;
}

export interface TrifectaPick {
  /** "1-3-5" の形。1着-2着-3着の艇番。 */
  combo: string;
  /** モデルがこの並びに与えた確率。 */
  prob: number;
  /** 表示時点の三連単オッズ。 */
  odds: number;
  /** prob × odds。1.0超で理論上プラス。 */
  ev: number;
}

export interface Venue {
  code: string;
  name: string;
  races: Race[];
}

export interface DayData {
  date: string;
  updated_at?: string;
  venues: Venue[];
}
