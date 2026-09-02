import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/**
 * Supabaseクライアント。
 *
 * 環境変数が無ければ null を返し、data.ts はローカルJSONにフォールバックする。
 * 手元では収集ジョブの出力をそのまま見られ、本番ではDBを見る、という
 * 二重運用を画面側に意識させないための仕組み。
 *
 * anonキーはブラウザに出る前提のもので、schema.sql のRLSにより
 * 読み取りだけが許可されている。書き込みは収集ジョブが service_role で行う。
 */

// 環境変数の貼り付けでは、末尾のスラッシュや前後の空白・改行が
// 混入しやすい。末尾スラッシュが付いていると要求パスが
// "//rest/v1/..." となり "Invalid path specified in request URL" で
// 全ページが落ちる。設定ミスに強くするため、ここで正規化する。
const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim().replace(/\/+$/, "");
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.trim();

let client: SupabaseClient | null = null;

/**
 * URLの形を検証する。
 *
 * 正しいのは https://<プロジェクトID>.supabase.co の形だけ。
 * ダッシュボードのアドレスバーの値を貼ると
 * https://supabase.com/dashboard/project/<ID> になり、Supabaseは
 * "Invalid path specified in request URL" という原因の分かりにくい
 * エラーを返す。設定ミスをここで名指しする。
 */
function assertProjectUrl(value: string): void {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(
      `NEXT_PUBLIC_SUPABASE_URL がURLとして不正です: ${value}\n` +
        "https://<プロジェクトID>.supabase.co の形で設定してください。"
    );
  }

  if (parsed.hostname === "supabase.com" || parsed.hostname === "www.supabase.com") {
    throw new Error(
      "NEXT_PUBLIC_SUPABASE_URL にダッシュボードのURLが設定されています。\n" +
        "ブラウザのアドレスバーの値ではなく、Supabaseの " +
        "Project Settings > API にある Project URL " +
        "(https://<プロジェクトID>.supabase.co) を設定してください。"
    );
  }

  if (parsed.pathname !== "/" && parsed.pathname !== "") {
    throw new Error(
      `NEXT_PUBLIC_SUPABASE_URL に余分なパスが含まれています: ${parsed.pathname}\n` +
        "https://<プロジェクトID>.supabase.co までにしてください（/rest/v1 などは不要）。"
    );
  }

  if (!parsed.hostname.endsWith(".supabase.co")) {
    throw new Error(
      `NEXT_PUBLIC_SUPABASE_URL のホスト名が想定と異なります: ${parsed.hostname}\n` +
        "通常は <プロジェクトID>.supabase.co です。"
    );
  }
}

export function getSupabase(): SupabaseClient | null {
  if (!url || !anonKey) return null;
  if (!client) {
    assertProjectUrl(url);
    client = createClient(url, anonKey, {
      auth: { persistSession: false },
    });
  }
  return client;
}

export const usingSupabase = Boolean(url && anonKey);
