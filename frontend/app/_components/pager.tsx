"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { PAGE_TIERS, pageItems, pageRange, pageSizeFor } from "@/lib/pages";

// One media query per tier boundary: they fire only when the window's height crosses one, and the
// size is read from the tiers, so a table reloads only then, not on every pixel of a resize.
const BOUNDARIES = PAGE_TIERS.filter((t) => t.minHeight > 0).map(
  (t) => `(min-height: ${t.minHeight}px)`,
);

function subscribeHeight(onChange: () => void): () => void {
  const queries = BOUNDARIES.map((q) => window.matchMedia(q));
  for (const q of queries) q.addEventListener("change", onChange);
  // Also on resize, for an environment that resizes without firing the queries' change (some
  // emulated viewports). Cheap: the snapshot is the tier's size, so only a new tier re-renders.
  window.addEventListener("resize", onChange);
  return () => {
    for (const q of queries) q.removeEventListener("change", onChange);
    window.removeEventListener("resize", onChange);
  };
}

/** What the server renders with, before the window's height is known: the common tier. */
const SERVER_PAGE_SIZE = 15;

/** Rows per page for this window's height (`PAGE_TIERS`), changing only at a tier boundary. */
export function usePageSize(): number {
  return useSyncExternalStore(
    subscribeHeight,
    () => pageSizeFor(window.innerHeight),
    () => SERVER_PAGE_SIZE,
  );
}

/** A small button's hit area, taller by a pseudo-element; never wider, so neighbours never overlap. */
const HIT =
  "relative after:absolute after:inset-x-0 after:-inset-y-1.5 after:content-['']";

/**
 * Under a paged table: which rows it shows ("Showing 26–50 of 312 runs") and, when there is more
 * than one page, Previous, the page numbers (the ends and the current page's neighbours, a gap for
 * the rest) and Next. The current page is marked for screen readers too.
 */
export function Pager({
  page,
  count,
  total,
  size,
  noun,
  onPage,
}: {
  page: number;
  /** Rows per page. */
  size: number;
  /** How many pages the list has. */
  count: number;
  /** How many rows the whole list has. */
  total: number;
  /** What a row is, singular ("run", "failed trace"). */
  noun: string;
  onPage: (page: number) => void;
}) {
  const { from, to } = pageRange(page, total, size);
  const nouns = total === 1 ? noun : `${noun}s`;
  return (
    <nav
      aria-label={`Pages of ${noun}s`}
      className="flex flex-wrap items-center justify-between gap-3"
    >
      <p className="type-body text-muted-foreground tabular-nums">
        Showing {from}–{to} of {total} {nouns}
      </p>
      {count > 1 && (
        <ul className="flex flex-wrap items-center gap-2">
          <li>
            <Button
              variant="ghost"
              size="sm"
              disabled={page === 1}
              onClick={() => onPage(page - 1)}
              className={HIT}
            >
              <ChevronLeft aria-hidden="true" />
              {/* Only the arrow on a phone, so the pager stays one line; the word is still read. */}
              <span className="max-sm:sr-only">Previous</span>
            </Button>
          </li>
          {pageItems(page, count).map((item, i) =>
            item === "gap" ? (
              <li
                // Two gaps at most, one each side of the current page.
                key={i < 3 ? "gap-before" : "gap-after"}
                aria-hidden="true"
                className="type-body px-1 text-muted-foreground"
              >
                …
              </li>
            ) : (
              <li key={item}>
                <Button
                  variant={item === page ? "secondary" : "ghost"}
                  size="sm"
                  aria-current={item === page ? "page" : undefined}
                  aria-label={`Page ${item}`}
                  onClick={() => onPage(item)}
                  className={`${HIT} min-w-8 tabular-nums`}
                >
                  {item}
                </Button>
              </li>
            ),
          )}
          <li>
            <Button
              variant="ghost"
              size="sm"
              disabled={page === count}
              onClick={() => onPage(page + 1)}
              className={HIT}
            >
              <span className="max-sm:sr-only">Next</span>
              <ChevronRight aria-hidden="true" />
            </Button>
          </li>
        </ul>
      )}
    </nav>
  );
}
