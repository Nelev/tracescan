/**
 * The signed-in person's Clerk session token, for the backend: every call but health sends it as
 * `Authorization: Bearer`, and the backend reads who is asking from it alone.
 *
 * Clerk lives in React, this module does not: `ApiAuth` (app/_components/api-auth.tsx) hands it
 * Clerk's `getToken` once Clerk has loaded. A call made before then waits for it, so a page that
 * loads its data on first render does not go out unsigned. A token lives about a minute, so it is
 * asked for on every call; Clerk caches and refreshes it.
 */

/** Clerk's `getToken`: the current session token, or null when signed out. */
export type TokenSource = () => Promise<string | null>;

let provide: (source: TokenSource) => void = () => {};
let source: Promise<TokenSource> = new Promise((resolve) => {
  provide = resolve;
});

/** Where tokens come from from now on; the first call also releases the calls waiting for it. */
export function setTokenSource(next: TokenSource): void {
  provide(next);
  source = Promise.resolve(next);
}

/**
 * `init` with the session token as `Authorization: Bearer`. Signed out, or when Clerk cannot give
 * a token, `init` goes as it is and the backend answers 401.
 */
export async function withSessionToken(
  init: RequestInit,
): Promise<RequestInit> {
  let token: string | null = null;
  try {
    token = await (await source)();
  } catch {
    // Clerk could not refresh the token (offline, say): the backend's 401 says the rest.
  }
  if (!token) return init;
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return { ...init, headers };
}
