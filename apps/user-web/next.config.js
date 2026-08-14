/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 백엔드는 별도 오리진(NEXT_PUBLIC_API_BASE_URL, frontend/lib/api-client.ts 참고)에서
  // 서비스하는 독립형 연계 MVP를 전제로 한다 (인터페이스 명세 1절). 이미지 원격 도메인이
  // 필요해지면(부스·제품 이미지) 이 배열에 추가한다.
  images: {
    remotePatterns: [],
  },
};

module.exports = nextConfig;
