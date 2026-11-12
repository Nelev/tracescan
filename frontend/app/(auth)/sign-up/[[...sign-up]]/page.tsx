import { SignUp } from "@clerk/nextjs";
import { Suspense } from "react";

/** The way in. Sign-up is by invitation only (set in the Clerk dashboard); this page is where an invitation's link lands. Outside the shell: nothing of the app shows until then. */
export default function SignUpPage() {
  return (
    <main className="flex min-h-dvh flex-1 items-center justify-center px-4 py-10">
      {/* Clerk routes its own steps by the pathname, which is known only per request. */}
      <Suspense
        fallback={<p className="type-body text-muted-foreground">Loading…</p>}
      >
        <SignUp />
      </Suspense>
    </main>
  );
}
