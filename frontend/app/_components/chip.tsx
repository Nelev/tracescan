import { Check, type LucideIcon, Square, UserCheck, X } from "lucide-react";
import type { ReactNode } from "react";
import type { StatusTone } from "@/lib/runs";
import { cn } from "@/lib/utils";

/**
 * The status palette, one recipe per tone: the tone as text, at 10% behind it, and as the border.
 * See the color roles in globals.css. Spelled out in full so Tailwind finds each class.
 */
export const CHIP_TONE: Record<StatusTone, string> = {
  neutral:
    "border-muted-foreground/30 bg-muted-foreground/10 text-muted-foreground",
  info: "border-info/40 bg-info/10 text-info",
  warning: "border-warning/40 bg-warning/10 text-warning",
  success: "border-success/35 bg-success/10 text-success",
  destructive: "border-destructive/40 bg-destructive/10 text-destructive",
  stopped: "border-stopped/40 bg-stopped/10 text-stopped",
};

/** Each tone as a solid fill: the bars of the pipeline and of the run outcomes. */
export const TONE_FILL: Record<StatusTone, string> = {
  neutral: "bg-track",
  info: "bg-info",
  warning: "bg-warning",
  success: "bg-success",
  destructive: "bg-destructive",
  stopped: "bg-stopped",
};

const SIZE = {
  md: { box: "h-7 gap-2 px-3", icon: "size-4" },
  sm: { box: "h-6 gap-1.5 px-2", icon: "size-3.5" },
};

// Info's mark is a dot, drawn below; neutral has none.
const ICON: Partial<Record<StatusTone, LucideIcon>> = {
  warning: UserCheck,
  success: Check,
  destructive: X,
  stopped: Square,
};

/** Each tone's mark, so a status never rests on its color alone. */
function Mark({
  tone,
  live,
  className,
}: {
  tone: StatusTone;
  live: boolean;
  className: string;
}) {
  if (tone === "info") {
    return (
      <span
        className={cn(
          "size-2 rounded-full bg-current",
          live && "motion-safe:animate-pulse",
        )}
        aria-hidden="true"
      />
    );
  }
  const Icon = ICON[tone];
  return Icon ? <Icon className={className} aria-hidden="true" /> : null;
}

/** A status chip. `live` pulses the info dot: something is happening right now. */
export function Chip({
  tone,
  size = "md",
  live = false,
  children,
}: {
  tone: StatusTone;
  size?: keyof typeof SIZE;
  live?: boolean;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex max-w-full items-center rounded-full border",
        SIZE[size].box,
        CHIP_TONE[tone],
      )}
    >
      <Mark tone={tone} live={live} className={SIZE[size].icon} />
      <span
        className="type-h4 min-w-0 truncate text-current"
        title={typeof children === "string" ? children : undefined}
      >
        {children}
      </span>
    </span>
  );
}
