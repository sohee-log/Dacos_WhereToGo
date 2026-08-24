import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'https://dacos-wheretogo.onrender.com/api/:path*', // 배포 서버로 토스
      },
    ];
  },
};

export default nextConfig;