import { cn } from "@/lib/utils";

// The parts a page of numbers is built from (the dashboard, the results page).

/** One headline number: what it is, the number, and what it is out of. */
export function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="surface flex flex-col gap-1 rounded-xl border p-4">
      <span className="type-h4">{label}</span>
      <span className="type-h1 font-mono tabular-nums">{value}</span>
      <span className="type-body text-muted-foreground">{hint}</span>
    </div>
  );
}

/** A titled panel of the page, its heading named for assistive technology. */
export function Panel({
  title,
  note,
  children,
  className,
}: {
  title: string;
  note?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const id = `panel-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section
      aria-labelledby={id}
      className={cn(
        "surface flex min-w-0 flex-col gap-4 rounded-xl border p-4",
        className,
      )}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id={id}>{title}</h2>
        {note && (
          <span className="type-body text-muted-foreground">{note}</span>
        )}
      </div>
      {children}
    </section>
  );
}
