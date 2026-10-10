/**
 * Sign-in with OIDC: the authorization code flow with PKCE, against Dex.
 *
 * The web app is a public client, so it holds no secret: a random verifier, sent hashed
 * on the way out and in full on the code exchange, proves the code is ours. The access
 * token lives in sessionStorage, so it ends with the tab.
 */

const ISSUER = import.meta.env.VITE_OIDC_ISSUER ?? "http://127.0.0.1:5556/dex";
const CLIENT_ID = import.meta.env.VITE_OIDC_CLIENT_ID ?? "ace-web";
const SCOPE = "openid email profile groups";
const TOKEN_KEY = "ace.access_token";
const PENDING_KEY = "ace.pending_sign_in";
const VERIFIER_BYTES = 32;

interface PendingSignIn {
  state: string;
  verifier: string;
}

interface Endpoints {
  authorization_endpoint: string;
  token_endpoint: string;
}

function redirectUri(): string {
  return `${window.location.origin}/`;
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomString(): string {
  return base64Url(crypto.getRandomValues(new Uint8Array(VERIFIER_BYTES)));
}

async function challengeOf(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

async function endpoints(): Promise<Endpoints> {
  const response = await fetch(`${ISSUER}/.well-known/openid-configuration`);
  if (!response.ok) throw new Error(`sign-in is unavailable (${response.status})`);
  const body: unknown = await response.json();
  const e = body as Record<string, unknown>;
  if (typeof e.authorization_endpoint !== "string" || typeof e.token_endpoint !== "string") {
    throw new Error("the sign-in provider sent an unexpected configuration");
  }
  return { authorization_endpoint: e.authorization_endpoint, token_endpoint: e.token_endpoint };
}

export function accessToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function signOut(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

/** Leave for the provider's login page. */
export async function signIn(): Promise<void> {
  const pending: PendingSignIn = { state: randomString(), verifier: randomString() };
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending));
  const { authorization_endpoint } = await endpoints();
  const params = new URLSearchParams({
    response_type: "code",
    client_id: CLIENT_ID,
    redirect_uri: redirectUri(),
    scope: SCOPE,
    state: pending.state,
    code_challenge: await challengeOf(pending.verifier),
    code_challenge_method: "S256",
  });
  window.location.assign(`${authorization_endpoint}?${params}`);
}

function takePending(): PendingSignIn | null {
  const raw = sessionStorage.getItem(PENDING_KEY);
  sessionStorage.removeItem(PENDING_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PendingSignIn>;
    if (typeof parsed.state === "string" && typeof parsed.verifier === "string") {
      return { state: parsed.state, verifier: parsed.verifier };
    }
  } catch (e) {
    console.error("pending sign-in was not JSON", e);
  }
  return null;
}

async function exchange(code: string, verifier: string): Promise<string> {
  const { token_endpoint } = await endpoints();
  const response = await fetch(token_endpoint, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(),
      client_id: CLIENT_ID,
      code_verifier: verifier,
    }),
  });
  if (!response.ok) throw new Error(`sign-in failed (${response.status})`);
  const body = (await response.json()) as Record<string, unknown>;
  if (typeof body.access_token !== "string") throw new Error("sign-in returned no token");
  return body.access_token;
}

/**
 * On the way back from the provider, trade the code for a token and clean the URL.
 * Does nothing when the URL carries no sign-in reply.
 */
export async function finishSignIn(): Promise<void> {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const failure = url.searchParams.get("error");
  if (!code && !failure) return;
  window.history.replaceState(null, "", url.pathname);
  const pending = takePending();
  if (failure) throw new Error(`sign-in failed: ${failure}`);
  if (!pending || !code || state !== pending.state) {
    throw new Error("sign-in reply did not match the request; sign in again");
  }
  sessionStorage.setItem(TOKEN_KEY, await exchange(code, pending.verifier));
}
