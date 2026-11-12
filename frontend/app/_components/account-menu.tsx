"use client";

import { UserButton } from "@clerk/nextjs";
import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * Who is signed in, and the way out: Clerk's account button. Clerk mounts it into a host element on
 * the client only, so it renders nothing until hydration is done, or the server's HTML and the
 * client's first render would differ once Clerk has loaded first.
 */
export function AccountMenu() {
  const hydrated = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  return hydrated ? <UserButton /> : null;
}
