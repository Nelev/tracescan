import type { ReactNode } from "react";
import { TraceField } from "./trace-field";

/**
 * The frame of the way in (sign-in, sign-up): the pipeline playing behind the form
 * (`TraceField`). Outside the app shell.
 */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative isolate flex min-h-dvh flex-1 flex-col">
      <TraceField className="pointer-events-none fixed inset-0 -z-10 size-full motion-safe:animate-in motion-safe:fade-in motion-safe:duration-1000" />
      {children}
    </div>
  );
}
