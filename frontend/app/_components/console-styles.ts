// Looks the console's parts share, so they cannot drift apart.

/**
 * The console fills the window: the page, the card, the tabs and the box around the panes are
 * one flex column, and the box takes whatever height is left (never under 24rem, below which the
 * page scrolls instead). Each tab's panel is a `PANE_SLOT` in that box, and its pane fills it
 * with `PANE_HEIGHT`, scrolling inside, so switching tabs does not move the page.
 */
export const PANE_SLOT = "flex min-h-0 flex-1 flex-col";
export const PANE_HEIGHT = "min-h-0 flex-1";

/** A cell of the console's tables (Runs, Traces), and a cell that holds a number. */
export const CELL = "px-4 py-2 whitespace-nowrap";
export const NUMERIC = "text-right tabular-nums";
