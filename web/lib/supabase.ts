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

export function getSupabase(): SupabaseClient | null {
  if (!url || !anonKey) return null;
  if (!client) {
    client = createClient(url, anonKey, {
      auth: { persistSession: false },
    });
  }
  return client;
}

export const usingSupabase = Boolean(url && anonKey);
