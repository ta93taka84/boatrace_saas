-- ボートレース分析SaaS Supabaseスキーマ
--
-- 設計方針（半自動・省力化を最優先）:
--   * 自然キー (race_date, venue_code, race_no) で冪等にupsertできる形にする。
--     取り込みが途中で落ちても、同じコマンドを再実行すれば正しい状態に収束する。
--   * 三連単120通りのような細かいデータは行に展開せずJSONBに畳む。
--     1レース120行 × 156レース/日 = 年間680万行を避け、無料枠の容量と
--     マイグレーションの手間を抑える。分析はJSONB演算子で十分足りる。
--   * オッズは締切に向けて動くので履歴を残す(odds_snapshots)。他は1レース1行。
--   * 予測は model_version 付きで積む。較正をやり直しても過去の予測を
--     壊さず、モデル間の成績比較がSQLだけでできる。

-- ---------------------------------------------------------------- 会場マスタ

create table if not exists venues (
  code text primary key,          -- '01'〜'24'
  name text not null
);

insert into venues (code, name) values
  ('01','桐生'),('02','戸田'),('03','江戸川'),('04','平和島'),
  ('05','多摩川'),('06','浜名湖'),('07','蒲郡'),('08','常滑'),
  ('09','津'),('10','三国'),('11','びわこ'),('12','住之江'),
  ('13','尼崎'),('14','鳴門'),('15','丸亀'),('16','児島'),
  ('17','宮島'),('18','徳山'),('19','下関'),('20','若松'),
  ('21','芦屋'),('22','福岡'),('23','唐津'),('24','大村')
on conflict (code) do update set name = excluded.name;

-- -------------------------------------------------------------------- レース

create table if not exists races (
  id             bigserial primary key,
  race_date      date not null,
  venue_code     text not null references venues(code),
  race_no        smallint not null check (race_no between 1 and 12),

  -- 投票締切。朝の出走表取得時点で分かる。締切順の一覧に使う。
  closes_at      time,

  -- 直前情報の気象。展示前はNULL。
  weather        text,
  temperature    numeric(4,1),
  water_temp     numeric(4,1),
  wind_speed     numeric(4,1),
  wind_dir_code  smallint,        -- 公式サイトの is-windNN。17は無風。
  wave_height    numeric(5,1),

  fetched_at     timestamptz not null default now(),
  unique (race_date, venue_code, race_no)
);

create index if not exists races_date_idx on races (race_date desc);

-- ------------------------------------------------------------------ 出走選手

create table if not exists race_entries (
  race_id          bigint not null references races(id) on delete cascade,
  lane             smallint not null check (lane between 1 and 6),

  racer_id         text,
  name             text,
  class            text,          -- A1 / A2 / B1 / B2
  branch           text,
  age              smallint,
  weight           numeric(4,1),

  f_count          smallint,      -- フライング
  l_count          smallint,      -- 出遅れ
  avg_st           numeric(4,2),

  win_rate_all     numeric(4,2),
  in2_rate_all     numeric(5,2),
  in3_rate_all     numeric(5,2),
  win_rate_venue   numeric(4,2),
  in2_rate_venue   numeric(5,2),
  in3_rate_venue   numeric(5,2),

  motor_no         smallint,
  motor_in2_rate   numeric(5,2),
  motor_in3_rate   numeric(5,2),
  boat_no          smallint,
  boat_in2_rate    numeric(5,2),
  boat_in3_rate    numeric(5,2),

  -- 直前情報。展示が出るまではNULL。
  exhibit_time     numeric(4,2),
  tilt             numeric(3,1),

  primary key (race_id, lane)
);

-- -------------------------------------------------------------------- オッズ
-- 締切に向けて動くため履歴として積む。最新1件を見るのが基本。

create table if not exists odds_snapshots (
  id           bigserial primary key,
  race_id      bigint not null references races(id) on delete cascade,
  captured_at  timestamptz not null default now(),

  -- インプライド確率の総和。正常値は約1.334(=1/0.75)。
  -- これが1.33前後から外れていたらオッズの取りこぼしを疑う。取り込み時の健全性チェックに使う。
  overround    numeric(6,4),

  market_prob  jsonb not null,   -- {"1":0.3462,...,"6":0.0441} 合計1.0
  trifecta     jsonb not null    -- {"1-2-3":9.6,...} 120通り
);

create index if not exists odds_race_captured_idx
  on odds_snapshots (race_id, captured_at desc);

-- ---------------------------------------------------------------------- 結果

create table if not exists race_results (
  race_id      bigint primary key references races(id) on delete cascade,
  winner_lane  smallint check (winner_lane between 1 and 6),
  finish       jsonb not null,   -- {"1":1,"6":2,...} 艇番 -> 着順
  kimarite     text,             -- 逃げ / 差し / まくり など
  payouts      jsonb,            -- {"3連単":{"combo":"1-6-2","payout":9480,...}}
  recorded_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------- 予測
-- model_version を付けて積む。較正のやり直しで過去分を消さない。

create table if not exists predictions (
  id             bigserial primary key,
  race_id        bigint not null references races(id) on delete cascade,
  model_version  text not null,
  created_at     timestamptz not null default now(),

  model_prob     jsonb not null,  -- {"1":0.5647,...} 合計1.0
  ev             jsonb,           -- {"1":1.223,...} 予測勝率/市場勝率*0.75
  top_lane       smallint,
  top_ev         numeric(6,3),

  -- そのモデルがバックテストで市場オッズを上回っているか。
  -- falseの予測を公開画面に出してはならない。
  calibrated     boolean not null default false,

  unique (race_id, model_version)
);

create index if not exists predictions_version_idx
  on predictions (model_version, created_at desc);

-- ------------------------------------------------------------ モデル成績集計
-- 較正が進んだかを1クエリで確認するためのビュー。
-- 的中率だけでなくBrierを見る（自信度まで含めて正しいかが分かる）。

create or replace view model_performance as
select
  p.model_version,
  count(*)                                             as races,
  avg((p.top_lane = r.winner_lane)::int)               as top_pick_hit_rate,
  avg((
    select sum(power(
      coalesce((p.model_prob ->> lane::text)::numeric, 0)
        - (case when lane = r.winner_lane then 1 else 0 end),
      2))
    from generate_series(1, 6) as lane
  ))                                                   as brier
from predictions p
join race_results r using (race_id)
group by p.model_version;

-- ------------------------------------------------------------------- 公開制御
-- Supabaseはanonキーがブラウザに露出するため、RLSを有効にして
-- 「結果が確定した過去レースだけ読める」状態にする。書き込みは
-- service_roleキーを持つ収集ジョブのみ（service_roleはRLSを迂回する）。

alter table venues         enable row level security;
alter table races          enable row level security;
alter table race_entries   enable row level security;
alter table odds_snapshots enable row level security;
alter table race_results   enable row level security;
alter table predictions    enable row level security;

create policy "public read venues"  on venues        for select using (true);
create policy "public read races"   on races         for select using (true);
create policy "public read entries" on race_entries  for select using (true);
create policy "public read odds"    on odds_snapshots for select using (true);
create policy "public read results" on race_results  for select using (true);

-- 未較正の予測は公開しない。CALIBRATED=false のまま出すと
-- 単なるモデル誤差を「期待値プラス」として見せることになる。
create policy "public read calibrated predictions" on predictions
  for select using (calibrated = true);
