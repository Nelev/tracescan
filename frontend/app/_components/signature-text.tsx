import { Fragment } from "react";
import type { SignaturePart } from "@/lib/run-overview";

const MASKED = {
  number: { shown: "n", meaning: "a number that differs between the traces" },
  quoted: {
    shown: "‘…’",
    meaning: "a quoted value that differs between the traces",
  },
} as const;

/**
 * A cluster signature's error as a reader can take it in (its parts from `signatureMasks`): the
 * values the clustering masked read as muted placeholders (`n`, `‘…’`) that say what they stand
 * for, not as `#` and `'x'`.
 */
export function SignatureText({ parts }: { parts: SignaturePart[] }) {
  return parts.map((part, i) => (
    // biome-ignore lint/suspicious/noArrayIndexKey: the parts of one fixed string, never reordered
    <Fragment key={i}>
      {part.kind === "text" ? (
        part.text
      ) : (
        <abbr
          title={MASKED[part.kind].meaning}
          className="text-muted-foreground italic no-underline"
        >
          <span aria-hidden="true">{MASKED[part.kind].shown}</span>
          <span className="sr-only">{MASKED[part.kind].meaning}</span>
        </abbr>
      )}
    </Fragment>
  ));
}
