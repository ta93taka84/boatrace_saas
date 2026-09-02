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
  model_prob?: Record<string, number>;
  ev?: Record<string, number>;
  top_lane?: number;
  top_ev?: number;
  result?: RaceResult;
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
