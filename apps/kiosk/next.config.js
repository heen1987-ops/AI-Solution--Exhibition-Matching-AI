/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 백엔드는 별도 오리진(NEXT_PUBLIC_API_BASE_URL, lib/api-client.ts 참고)에서 서비스한다.
  images: {
    remotePatterns: [],
  },
};

module.exports = nextConfig;
