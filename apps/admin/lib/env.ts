/**
 * Centralised read of the admin app's public build/environment settings.
 *
 * ADM-GROUP-001 scope: `/console` uses apiBaseUrl for API-first admin
 * operations. `/health` still displays these values without making requests.
 */
export interface AdminEnvInfo {
  appName: string;
  apiBaseUrl: string;
  environment: string;
  contractVersion: string;
}

export function getAdminEnvInfo(): AdminEnvInfo {
  return {
    appName: process.env.NEXT_PUBLIC_ADMIN_APP_NAME ?? "백주대간 관리자",
    apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
    environment: process.env.NEXT_PUBLIC_ENVIRONMENT ?? "local",
    contractVersion: process.env.NEXT_PUBLIC_CONTRACT_VERSION ?? "1.0.0",
  };
}
