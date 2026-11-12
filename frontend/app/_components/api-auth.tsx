"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";
import { setTokenSource } from "@/lib/session-token";

/**
 * Hands Clerk's session tokens to the API client (lib/session-token.ts) once Clerk has loaded.
 * Renders nothing; calls made before then wait for it.
 */
export function ApiAuth() {
  const { isLoaded, getToken } = useAuth();
  useEffect(() => {
    if (isLoaded) setTokenSource(() => getToken());
  }, [isLoaded, getToken]);
  return null;
}
