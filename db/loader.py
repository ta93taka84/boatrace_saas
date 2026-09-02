"""
スクレイプ結果をSupabase(PostgreSQL)へ取り込む。

すべてUPSERTなので、途中で落ちても同じコマンドを再実行すれば正しい状態に収束する。
GitHub Actionsからは環境変数 DATABASE_URL（service_role相当の接続文字列）を渡す。

使い方:
  py -3 -m db.loader output/20260902.json
  py -3 -m db.loader output/backtest.jsonl --results
"""
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from psycopg.types.json import Jsonb

MODEL_VERSION = "baseline-v1"


def connect():
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL が未設定です。Supabaseの接続文字列を渡してください。")

    try:
        return psycopg.connect(dsn)
    except psycopg.OperationalError as e:
        # DATABASE_URLはシークレットなのでログに出ない。そのままだと
        # 何が悪いのか分からないため、パスワードを伏せたホスト名だけ出す。
        raise SystemExit(f"{_describe_dsn(dsn)}\n接続に失敗しました: {e}") from e


def _describe_dsn(dsn: str) -> str:
    """接続先の診断情報を、認証情報を伏せた形で組み立てる。"""
    parsed = urlparse(dsn)
    host, port = parsed.hostname or "?", parsed.port or "?"
    lines = [f"接続先: {host}:{port} (user={parsed.username or '?'})"]

    # ホスト名にドットが無いのは、まともなFQDNではないということ。
    # パスワードに @ などのURL区切り文字が入っていると、そこが
    # ホスト名の開始と誤解釈され、断片が host として取り出される。
    if "." not in host:
        lines.append(
            f"ホスト名 '{host}' は不正です。パスワードに @ # ? / : などの記号が\n"
            "含まれていると、接続文字列の解析が壊れてこの状態になります。\n"
            "対処: Supabaseでデータベースパスワードを英数字のみに変更するのが\n"
            "確実です（Project Settings > Database > Reset database password）。\n"
            "パスワードを変えたくない場合は記号をパーセントエンコードしてください\n"
            "（@ は %40、# は %23、? は %3F、/ は %2F、: は %3A）。"
        )
    elif "pooler" not in host:
        lines.append(
            "ホスト名に 'pooler' が含まれていません。Supabaseの Direct connection は\n"
            "IPv6専用で、GitHub ActionsのランナーはIPv4のみのため接続できません。\n"
            "Supabaseの Connect から 'Session pooler' の接続文字列を選び直してください。"
        )
    if parsed.port == 6543:
        lines.append(
            "ポート6543は Transaction pooler です。psycopgのプリペアドステートメントと\n"
            "相性が悪いため、ポート5432の Session pooler を使ってください。"
        )
    if parsed.password and parsed.password.startswith("["):
        lines.append(
            "パスワードが [YOUR-PASSWORD] のままです。実際のパスワードに\n"
            "置き換えてください（角括弧も削除）。"
        )
    return "\n".join(lines)


def load_pipeline_output(path: Path):
    """pipeline.py や jobs.py が出力した日次JSONを取り込む。"""
    # 締切が近いレースが無い時間帯は prerace が何も書かない。
    # 「取り込むものが無い」は正常な状態なので、失敗にしない。
    # ここで落とすと、異常が無いのに失敗通知が飛んでしまう。
    if not path.exists():
        print(f"{path} がありません。取り込むデータなしとして終了します。")
        return

    data = json.loads(path.read_text(encoding="utf-8"))
    race_date = _to_date(data["date"])

    with connect() as conn, conn.cursor() as cur:
        races = entries = odds = preds = 0
        for venue in data["venues"]:
            for race in venue["races"]:
                race_id = _upsert_race(cur, race_date, venue["code"], race)
                races += 1
                entries += _upsert_entries(cur, race_id, race.get("racers", []))
                if race.get("market_prob"):
                    _insert_odds(cur, race_id, race)
                    odds += 1
                if race.get("model_prob"):
                    _upsert_prediction(cur, race_id, race)
                    preds += 1
        conn.commit()

    print(f"取り込み完了: races={races} entries={entries} odds={odds} predictions={preds}")


def load_results(path: Path):
    """backtest.py が収集したjsonlから結果だけを取り込む。"""
    with connect() as conn, conn.cursor() as cur:
        n = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            cur.execute(
                "select id from races where race_date=%s and venue_code=%s and race_no=%s",
                (_to_date(row["date"]), row["venue"], row["race_no"]),
            )
            found = cur.fetchone()
            if not found:
                continue  # レース本体が未取り込み
            cur.execute(
                """
                insert into race_results (race_id, winner_lane, finish, kimarite, payouts)
                values (%s, %s, %s, %s, %s)
                on conflict (race_id) do update set
                  winner_lane = excluded.winner_lane,
                  finish      = excluded.finish,
                  kimarite    = excluded.kimarite,
                  payouts     = excluded.payouts
                """,
                (found[0], row.get("winner_lane"), Jsonb(row.get("finish", {})),
                 row.get("kimarite"), Jsonb(row.get("payouts", {}))),
            )
            n += 1
        conn.commit()
    print(f"結果取り込み完了: {n}件")


def _upsert_race(cur, race_date, venue_code, race) -> int:
    cond = race.get("conditions") or {}
    cur.execute(
        """
        insert into races (race_date, venue_code, race_no, weather, temperature,
                           water_temp, wind_speed, wind_dir_code, wave_height)
        values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        on conflict (race_date, venue_code, race_no) do update set
          weather       = coalesce(excluded.weather,       races.weather),
          temperature   = coalesce(excluded.temperature,   races.temperature),
          water_temp    = coalesce(excluded.water_temp,    races.water_temp),
          wind_speed    = coalesce(excluded.wind_speed,    races.wind_speed),
          wind_dir_code = coalesce(excluded.wind_dir_code, races.wind_dir_code),
          wave_height   = coalesce(excluded.wave_height,   races.wave_height),
          fetched_at    = now()
        returning id
        """,
        (race_date, venue_code, race["race_no"], cond.get("weather"),
         cond.get("temperature"), cond.get("water_temp"), cond.get("wind_speed"),
         cond.get("wind_dir_code"), cond.get("wave_height")),
    )
    return cur.fetchone()[0]


ENTRY_FIELDS = [
    "racer_id", "name", "class", "branch", "age", "weight",
    "f_count", "l_count", "avg_st",
    "win_rate_all", "in2_rate_all", "in3_rate_all",
    "win_rate_venue", "in2_rate_venue", "in3_rate_venue",
    "motor_no", "motor_in2_rate", "motor_in3_rate",
    "boat_no", "boat_in2_rate", "boat_in3_rate",
    "exhibit_time", "tilt",
]


def _upsert_entries(cur, race_id, racers) -> int:
    if not racers:
        return 0
    # "class" は予約語なので引用符で囲む
    cols = ", ".join(f'"{f}"' if f == "class" else f for f in ENTRY_FIELDS)
    placeholders = ", ".join(["%s"] * len(ENTRY_FIELDS))
    # 展示タイム等は後から埋まるのでNULL上書きを避ける
    updates = ", ".join(
        f'{f} = coalesce(excluded.{f}, race_entries.{f})'
        for f in ENTRY_FIELDS if f != "class"
    ) + ', "class" = coalesce(excluded."class", race_entries."class")'

    for r in racers:
        cur.execute(
            f"""
            insert into race_entries (race_id, lane, {cols})
            values (%s, %s, {placeholders})
            on conflict (race_id, lane) do update set {updates}
            """,
            [race_id, r["lane"]] + [r.get(f) for f in ENTRY_FIELDS],
        )
    return len(racers)


def _insert_odds(cur, race_id, race):
    """オッズは時系列で積む（締切に向けて動くため）。"""
    cur.execute(
        """
        insert into odds_snapshots (race_id, overround, market_prob, trifecta)
        values (%s, %s, %s, %s)
        """,
        (race_id, race.get("overround"),
         Jsonb(_str_keys(race.get("market_prob", {}))),
         Jsonb(race.get("odds", {}))),
    )


def _upsert_prediction(cur, race_id, race):
    from scraper.scoring import CALIBRATED

    cur.execute(
        """
        insert into predictions (race_id, model_version, model_prob, ev,
                                 top_lane, top_ev, calibrated)
        values (%s,%s,%s,%s,%s,%s,%s)
        on conflict (race_id, model_version) do update set
          model_prob = excluded.model_prob,
          ev         = excluded.ev,
          top_lane   = excluded.top_lane,
          top_ev     = excluded.top_ev,
          calibrated = excluded.calibrated,
          created_at = now()
        """,
        (race_id, MODEL_VERSION,
         Jsonb(_str_keys(race.get("model_prob", {}))),
         Jsonb(_str_keys(race.get("ev", {}))),
         race.get("top_lane"), race.get("top_ev"), CALIBRATED),
    )


def _str_keys(d: dict) -> dict:
    """JSONBのキーは文字列に統一する（艇番がintで来る経路があるため）。"""
    return {str(k): v for k, v in d.items()}


def _to_date(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    target = Path(args[0])
    if "--results" in args:
        load_results(target)
    else:
        load_pipeline_output(target)
