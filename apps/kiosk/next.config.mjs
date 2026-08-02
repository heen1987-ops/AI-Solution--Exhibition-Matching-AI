/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 키오스크는 전용 디바이스(터치스크린 브라우저/웹뷰)에서만 구동되므로
  // 이번 Wave에서는 별도 output target(standalone 등)을 고정하지 않는다.
};

export default nextConfig;
