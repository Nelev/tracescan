import Link from "next/link";
import { AppShell } from "@/app/_components/app-shell";
import { buttonVariants } from "@/components/ui/button";

/** A path no page answers: inside the shell, so the nav is still there to go on from. */
export default function NotFound() {
  return (
    <AppShell>
      <div className="flex flex-col items-start gap-3">
        <h1>Page not found</h1>
        <p className="type-body text-muted-foreground">
          No page lives at this address. It may have been mistyped, or the link
          is out of date.
        </p>
        <Link href="/" className={buttonVariants({ variant: "outline" })}>
          Go to the dashboard
        </Link>
      </div>
    </AppShell>
  );
}
