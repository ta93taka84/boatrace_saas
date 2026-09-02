/** @type {import('next').NextConfig} */
const nextConfig = {
  // output/ の日次JSONを読むため、リポジトリルートを辿れるようにする
  outputFileTracingRoot: process.cwd() + "/..",
};
export default nextConfig;
