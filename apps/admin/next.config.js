/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // apps/api와 별도 오리진에서 서비스한다는 전제 (NEXT_PUBLIC_API_BASE_URL, lib/api-client.ts
  // 참고). apps/user-web/next.config.js와 동일한 전제를 따른다.
  images: {
    remotePatterns: [],
  },
};

module.exports = nextConfig;
