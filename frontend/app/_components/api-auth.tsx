"use client";

import { useAuth, useClerk } from "@clerk/nextjs";
import { useEffect } from "react";
import { setTokenSource } from "@/lib/session-token";

/**
 * Hands Clerk's session tokens to the API client (lib/session-token.ts) once Clerk has loaded.
 * Renders nothing; calls made before then wait for it.
 *
 * The source reads Clerk's session when a call is made, not when this rendered: `useAuth`'s
 * `getToken` belongs to its render, and right after signing in the page's first fetches run
 * before this component has rendered again, so a getter from the signed-out render would send
 * them without a token.
 */
export function ApiAuth() {
  const clerk = useClerk();
  const { isLoaded } = useAuth();
  useEffect(() => {
    if (isLoaded) {
      setTokenSource(async () => (await clerk.session?.getToken()) ?? null);
    }
  }, [isLoaded, clerk]);
  return null;
}
