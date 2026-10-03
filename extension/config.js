/* LC AutoSync configuration.
 * SERVICE_URL: Backend API URL. Production points at Vercel; for local
 * development change to "http://localhost:7337" (and allow it in the
 * manifest host_permissions + backend CORS dev regex).
 * GITHUB_CLIENT_ID: GitHub OAuth App client ID (public, safe to ship).
 * The client SECRET lives only in the backend environment (Vercel).
 */
const LC_CONFIG = {
  SERVICE_URL: "https://lc-auto-sync.vercel.app",
  GITHUB_CLIENT_ID: "Ov23liNSazqIujNGkUdz",
};
