// Looks the page's parts share, so they cannot drift apart.

/** A cell of the app's tables (runs, traces), and a cell that holds a number. */
export const CELL = "px-4 py-2 whitespace-nowrap";
export const NUMERIC = "text-right tabular-nums";

/** A table's head row: sticky over the rows it heads. */
export const HEAD =
  "sticky top-0 z-sticky bg-card [&_th]:border-b [&_th]:border-rule";

/** Text that reads as a link: an id that opens something on another page. */
/** Monochrome like the rest of the ink, so the underline (always there) is what says "link". */
export const LINK =
  "font-mono text-foreground underline decoration-muted-foreground/60 underline-offset-4 transition-colors hover:decoration-foreground focus-visible:decoration-2 focus-visible:decoration-foreground focus-visible:outline-none";

/** A segmented control: the list, and one of its options (a label around a radio). */
export const SEGMENT_LIST = "flex gap-1 rounded-lg border bg-muted p-1";
export const SEGMENT_ITEM =
  "type-body cursor-pointer rounded-md px-3 py-1.5 text-center text-muted-foreground transition-colors select-none hover:text-foreground has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring";
