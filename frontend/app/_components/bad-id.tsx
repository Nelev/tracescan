import { tracesPath } from "@/lib/traces";
import { BackLink } from "./back-link";

/**
 * A run or trace page whose id cannot be one: says so plainly instead of asking the server, which
 * would answer a 422 that reads like an outage.
 */
export function BadId({ id, kind }: { id: string; kind: "run" | "trace" }) {
  return (
    <div className="flex flex-col gap-3">
      {kind === "run" ? (
        <BackLink href="/runs">All runs</BackLink>
      ) : (
        <BackLink href={tracesPath(false)}>All traces</BackLink>
      )}
      <h1 className="font-mono [overflow-wrap:anywhere]">{id}</h1>
      <p role="alert" className="type-body text-destructive">
        This is not a {kind} id.{" "}
        {kind === "run"
          ? "A run id is a UUID, as in the Runs list."
          : "A trace id is letters, digits, dots, dashes or underscores, up to 64."}
      </p>
    </div>
  );
}
