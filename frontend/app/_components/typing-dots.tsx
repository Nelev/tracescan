import { cn } from "@/lib/utils";

/**
 * The typing indicator: three dots that rise in turn while the agent works. Still under
 * prefers-reduced-motion (the `typing-dot` utility in globals.css). `label` is what a screen
 * reader hears in its place.
 */
export function TypingDots({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 text-primary", className)}
    >
      <span className="typing-dot" aria-hidden="true" />
      <span className="typing-dot [animation-delay:150ms]" aria-hidden="true" />
      <span className="typing-dot [animation-delay:300ms]" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  );
}
