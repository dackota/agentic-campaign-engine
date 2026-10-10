/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** The OIDC issuer (Dex) the web app signs in with. */
  readonly VITE_OIDC_ISSUER?: string;
  readonly VITE_OIDC_CLIENT_ID?: string;
}
