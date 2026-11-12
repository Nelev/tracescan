import { SignIn } from "@clerk/nextjs";
import { Suspense } from "react";

/** The way in: where the proxy sends anyone signed out. Outside the shell: nothing of the app shows until then. */
export default function SignInPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-10">
      {/* Clerk routes its own steps by the pathname, which is known only per request. */}
      <Suspense
        fallback={<p className="type-body text-muted-foreground">Loading…</p>}
      >
        <SignIn />
      </Suspense>
    </main>
  );
}
