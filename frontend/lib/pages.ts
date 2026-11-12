// Paged lists (the runs and traces tables): which page holds which rows, and how a pager reads.
// Pure, so the arithmetic is tested here.

/** Rows on one page of a table, when nothing says how tall the window is. */
export const PAGE_SIZE = 25;

/**
 * Rows per page by the window's height, so a table about fills the screen above its pager: a row
 * is about 42px and the header, title, column heads, pager and footer take about 310px. Steps,
 * not a measured fit, so a page reloads only when the window crosses one. Tallest first.
 */
export const PAGE_TIERS: { minHeight: number; size: number }[] = [
  { minHeight: 1400, size: 25 },
  { minHeight: 1100, size: 20 },
  { minHeight: 800, size: 15 },
  { minHeight: 0, size: 10 },
];

/** The rows per page for a window this tall. */
export function pageSizeFor(height: number): number {
  for (const tier of PAGE_TIERS) if (height >= tier.minHeight) return tier.size;
  return PAGE_TIERS[PAGE_TIERS.length - 1].size;
}

/**
 * The page that holds a row (counted from 0) at a page size: where to land when the page size
 * changes, so the first row on screen stays on screen.
 */
export function pageForRow(row: number, size: number): number {
  return Math.floor(Math.max(0, row) / size) + 1;
}

/** One page of a list, and how many rows the whole list holds. */
export type Page<T> = { items: T[]; total: number };

/** A list's pages: at least one, so an empty list still reads as page 1 of 1. */
export function pageCount(total: number, size = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / size));
}

/** A page number held to the pages there are. */
export function clampPage(page: number, count: number): number {
  return Math.min(Math.max(1, page), count);
}

/** How many rows come before a page: what the server is asked to skip. */
export function pageOffset(page: number, size = PAGE_SIZE): number {
  return (page - 1) * size;
}

/** The rows a page shows, counted from 1 ("26–50 of 312"); 0 to 0 for an empty list. */
export function pageRange(
  page: number,
  total: number,
  size = PAGE_SIZE,
): { from: number; to: number } {
  if (total === 0) return { from: 0, to: 0 };
  return { from: pageOffset(page, size) + 1, to: Math.min(page * size, total) };
}

export type PageItem = number | "gap";

/**
 * The page numbers a pager shows: the first, the last, and the current one with its neighbours,
 * a gap where pages are left out (1 … 4 5 6 … 13). A gap stands for two pages or more, so a lone
 * missing page is shown as itself.
 */
export function pageItems(current: number, count: number): PageItem[] {
  const shown = new Set([1, count, current - 1, current, current + 1]);
  const pages = [...shown]
    .filter((p) => p >= 1 && p <= count)
    .sort((a, b) => a - b);
  const items: PageItem[] = [];
  for (const page of pages) {
    const before = items.at(-1);
    if (typeof before === "number" && page - before === 2) items.push(page - 1);
    else if (typeof before === "number" && page - before > 2) items.push("gap");
    items.push(page);
  }
  return items;
}

/**
 * A list's total from the server's `X-Total-Count` header. A server without it (one older than
 * paging) sends the whole list it has, so its length is the total.
 */
export function totalFrom(header: string | null, loaded: number): number {
  const total = header === null ? Number.NaN : Number(header);
  return Number.isInteger(total) && total >= 0 ? total : loaded;
}
