"use client";

import { RotateCcw } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  Component,
  type ReactNode,
  useState,
  useSyncExternalStore,
} from "react";
import { Button } from "@/components/ui/button";
import {
  type ClusterMap,
  clusterLabels,
  fidelityText,
  groupByCluster,
  hdbscanText,
  type MapPoint,
  PROJECTION_LABEL,
  pointRows,
  STAGE_MARK,
  traceCount,
} from "@/lib/cluster-map";
import {
  type ClusterDetail,
  type ClusterMethod,
  clusterTitle,
  METHOD_LABEL,
} from "@/lib/run-overview";
import { plural, shortId } from "@/lib/runs";
import { tracePath } from "@/lib/traces";
import { cn } from "@/lib/utils";
import { CELL, HEAD, LINK, SEGMENT_ITEM, SEGMENT_LIST } from "./styles";

// three.js is large: the scene loads only when a run with a map is opened, and never on the server.
const ClusterMap3D = dynamic(() => import("./cluster-map-3d"), {
  ssr: false,
  loading: () => (
    <p className="type-body grid h-full place-items-center text-muted-foreground">
      Loading the map…
    </p>
  ),
});

type View = "map" | "table";
const MAX_TRACE_LINKS = 6;

/**
 * The run's failed traces in 3D, as the clustering saw them: one mark per distinct failure, its
 * shape the stage that grouped it, its size how many traces share it. Picking a mark or a
 * cluster selects that cluster on the map; "Open finding" goes to its card. The table view
 * lists the same points for reading without the canvas.
 */
export function ClusterMapPanel({
  map,
  clusters,
  selected,
  onSelect,
  onOpenFinding,
}: {
  map: ClusterMap;
  clusters: ClusterDetail[];
  selected: string | null;
  onSelect: (clusterId: string | null) => void;
  onOpenFinding: (clusterId: string) => void;
}) {
  const [view, setView] = useState<View>("map");
  // null while rendering on the server: the check needs a browser.
  const webgl = useWebGL();
  // Set when the scene fails after the check (a lost or refused context): same as no WebGL.
  const [sceneFailed, setSceneFailed] = useState(false);
  const canDraw = webgl !== false && !sceneFailed;
  const shown: View = canDraw ? view : "table";
  // The mark picked on the map, if the selection came from one: its own traces are listed.
  const [picked, setPicked] = useState<number | null>(null);
  const [resets, setResets] = useState(0);
  // A new object per flight, so flying to the same cluster again moves the camera again.
  const [flight, setFlight] = useState<{ clusterId: string } | null>(null);
  const byId = new Map(clusters.map((c) => [c.cluster_id, c]));
  const points = map.points;
  const byCluster = groupByCluster(points);
  // The run's clusters in its own order, those on the map.
  const onMap = clusters.filter((c) => byCluster.has(c.cluster_id));
  const pickedPoint = picked === null ? null : (points[picked] ?? null);

  /** Every selection goes through here, so a picked mark never outlives its selection. */
  function select(clusterId: string | null, index: number | null = null) {
    setPicked(index);
    onSelect(clusterId);
  }

  function toggle(clusterId: string) {
    select(clusterId === selected ? null : clusterId);
  }

  function pick(index: number | null) {
    select(index === null ? null : points[index].cluster_id, index);
  }

  function pickCluster(clusterId: string, fly: boolean) {
    if (!fly) return toggle(clusterId);
    select(clusterId);
    setFlight({ clusterId });
  }

  function describe(point: MapPoint): string {
    return `${point.cluster_id} ${clusterTitle(byId.get(point.cluster_id))} · ${plural(point.trace_ids.length, "trace")} · ${hdbscanText(point)}`;
  }

  return (
    <section
      aria-labelledby="cluster-map"
      className="surface flex flex-col gap-3 rounded-xl border p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 id="cluster-map">Cluster map</h2>
          <p className="type-body text-muted-foreground">
            {PROJECTION_LABEL[map.projection]} projection of{" "}
            {plural(traceCount(points), "failed trace")} ·{" "}
            {fidelityText(map.trust)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {shown === "map" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setResets((n) => n + 1)}
            >
              <RotateCcw aria-hidden="true" />
              Reset view
            </Button>
          )}
          {canDraw && (
            <fieldset>
              <legend className="sr-only">Show the map as</legend>
              <div className={SEGMENT_LIST}>
                {(["map", "table"] as const).map((v) => (
                  <label
                    key={v}
                    className={cn(
                      SEGMENT_ITEM,
                      view === v && "bg-card text-foreground shadow-xs",
                    )}
                  >
                    <input
                      type="radio"
                      name="cluster-map-view"
                      value={v}
                      checked={view === v}
                      onChange={() => setView(v)}
                      className="sr-only"
                    />
                    {v === "map" ? "3D map" : "Table"}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </div>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="type-h4 mb-2">Clusters</legend>
        <div className="flex flex-wrap gap-1.5">
          {onMap.map((cluster) => {
            const id = cluster.cluster_id;
            const members = byCluster.get(id) ?? [];
            const on = id === selected;
            return (
              <button
                key={id}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(id)}
                className={cn(
                  "type-body inline-flex items-center gap-1.5 rounded-md border px-2 py-1 transition-colors hover:bg-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  on
                    ? "border-foreground text-foreground"
                    : "text-muted-foreground",
                )}
              >
                <StageMark stage={cluster.method} />
                <span className="font-mono">{id}</span>
                <span>{clusterTitle(cluster)}</span>
                <span className="tabular-nums">{traceCount(members)}</span>
              </button>
            );
          })}
        </div>
      </fieldset>

      {!canDraw && (
        <p className="type-body text-muted-foreground">
          {sceneFailed
            ? "The 3D map could not start in this browser."
            : "The 3D map needs WebGL, which this browser has turned off."}{" "}
          The table lists the same points.
        </p>
      )}
      {shown === "map" ? (
        <>
          <div
            role="img"
            aria-label={`3D map of ${plural(traceCount(points), "failed trace")} in ${plural(onMap.length, "cluster")}. The table view lists the same points.`}
            className="relative isolate h-80 overflow-hidden rounded-lg border md:h-[26rem]"
          >
            {webgl && (
              <SceneBoundary onError={() => setSceneFailed(true)}>
                <ClusterMap3D
                  points={points}
                  labels={clusterLabels(points, selected)}
                  selected={selected}
                  describe={describe}
                  onPick={pick}
                  onPickCluster={pickCluster}
                  flight={flight}
                  resetSignal={resets}
                />
              </SceneBoundary>
            )}
          </div>
          <div className="type-body flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-muted-foreground">
            <Legend />
            <span>
              Drag to turn, scroll to zoom; double-click a cluster's label to
              fly to it
            </span>
          </div>
        </>
      ) : (
        <PointTable
          points={points}
          byId={byId}
          selected={selected}
          onToggle={toggle}
        />
      )}

      {selected !== null && (
        <SelectionBar
          clusterId={selected}
          cluster={byId.get(selected)}
          points={byCluster.get(selected) ?? []}
          picked={pickedPoint}
          onFly={
            shown === "map" ? () => setFlight({ clusterId: selected }) : null
          }
          onOpen={() => onOpenFinding(selected)}
          onClear={() => select(null)}
        />
      )}

      <p className="type-body text-muted-foreground">
        HDBSCAN grouped the failures on every dimension of their embeddings;
        this is a 3D picture of that space, so a group that looks close here may
        not be. Squares were noise to HDBSCAN and grouped afterwards by failing
        step and error; rings fit no group.
      </p>
    </section>
  );
}

function SelectionBar({
  clusterId,
  cluster,
  points,
  picked,
  onFly,
  onOpen,
  onClear,
}: {
  clusterId: string;
  cluster: ClusterDetail | undefined;
  points: MapPoint[];
  picked: MapPoint | null;
  /** Fly the camera to the cluster; null when the 3D map is not showing. */
  onFly: (() => void) | null;
  onOpen: () => void;
  onClear: () => void;
}) {
  const traces = picked?.trace_ids ?? points.flatMap((p) => p.trace_ids);
  const shown = traces.slice(0, MAX_TRACE_LINKS);
  return (
    <div className="type-body flex flex-col gap-2 border-t border-rule pt-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="type-h3">
          <span className="font-mono">{clusterId}</span> {clusterTitle(cluster)}
          <span className="font-normal text-muted-foreground">
            {" "}
            · {plural(traceCount(points), "trace")}
            {cluster && ` · ${METHOD_LABEL[cluster.method]}`}
          </span>
        </span>
        <span className="flex gap-2">
          {onFly && (
            <Button variant="ghost" size="sm" onClick={onFly}>
              Fly to
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onOpen}>
            Open finding
          </Button>
          <Button variant="ghost" size="sm" onClick={onClear}>
            Clear
          </Button>
        </span>
      </div>
      {cluster && (
        <p
          className="truncate font-mono text-muted-foreground"
          title={cluster.signature}
        >
          {cluster.signature}
        </p>
      )}
      <p className="flex flex-wrap gap-x-3 gap-y-1">
        <span className="text-muted-foreground">
          {picked ? `This mark (${hdbscanText(picked)}):` : "Traces:"}
        </span>
        {shown.map((id) => (
          <Link key={id} href={tracePath(id)} className={LINK}>
            {shortId(id)}
          </Link>
        ))}
        {traces.length > shown.length && (
          <span className="text-muted-foreground">
            +{traces.length - shown.length} more
          </span>
        )}
      </p>
    </div>
  );
}

function PointTable({
  points,
  byId,
  selected,
  onToggle,
}: {
  points: MapPoint[];
  byId: Map<string, ClusterDetail>;
  selected: string | null;
  onToggle: (clusterId: string) => void;
}) {
  return (
    <div className="max-h-[26rem] overflow-auto overscroll-contain rounded-lg border">
      <table className="type-body w-full">
        <caption className="sr-only">
          The map's points: one row per distinct failure in a cluster
        </caption>
        <thead className={HEAD}>
          <tr className="text-left">
            <th className={CELL}>Cluster</th>
            <th className={CELL}>Grouped by</th>
            <th className={CELL}>Traces</th>
            <th className={CELL}>HDBSCAN</th>
          </tr>
        </thead>
        <tbody>
          {pointRows(points).map((point) => (
            <tr
              key={`${point.cluster_id}:${point.trace_ids[0]}`}
              className={cn(
                "border-b last:border-b-0",
                point.cluster_id === selected && "bg-hover",
              )}
            >
              <td className={CELL}>
                <button
                  type="button"
                  aria-pressed={point.cluster_id === selected}
                  onClick={() => onToggle(point.cluster_id)}
                  className="inline-flex items-center gap-1.5 text-left hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="font-mono">{point.cluster_id}</span>
                  <span className="text-muted-foreground">
                    {clusterTitle(byId.get(point.cluster_id))}
                  </span>
                </button>
              </td>
              <td className={CELL}>
                <span className="inline-flex items-center gap-1.5">
                  <StageMark stage={point.stage} />
                  {METHOD_LABEL[point.stage]}
                </span>
              </td>
              <td className={CELL}>
                <span className="flex gap-2">
                  {point.trace_ids.slice(0, 2).map((id) => (
                    <Link key={id} href={tracePath(id)} className={LINK}>
                      {shortId(id)}
                    </Link>
                  ))}
                  {point.trace_ids.length > 2 && (
                    <span className="text-muted-foreground">
                      +{point.trace_ids.length - 2}
                    </span>
                  )}
                </span>
              </td>
              <td className={cn(CELL, "text-muted-foreground")}>
                {hdbscanText(point, true)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1" aria-label="Marks">
      {(Object.keys(METHOD_LABEL) as ClusterMethod[]).map((stage) => (
        <li key={stage} className="inline-flex items-center gap-1.5">
          <StageMark stage={stage} />
          {METHOD_LABEL[stage]}
        </li>
      ))}
      <li>larger mark, more traces</li>
    </ul>
  );
}

/** The 2D twin of a stage's mark on the map, for the legend, the buttons and the table. */
function StageMark({ stage }: { stage: ClusterMethod }) {
  const mark = STAGE_MARK[stage];
  return (
    <svg viewBox="0 0 10 10" className="size-2.5 shrink-0" aria-hidden="true">
      {mark === "dot" && (
        <circle cx="5" cy="5" r="4.5" className="fill-current" />
      )}
      {mark === "square" && (
        <rect x="1" y="1" width="8" height="8" className="fill-current" />
      )}
      {mark === "ring" && (
        <circle
          cx="5"
          cy="5"
          r="3.5"
          className="fill-none stroke-current"
          strokeWidth="2"
        />
      )}
    </svg>
  );
}

let webglSupport: boolean | undefined;

/** Whether this browser can draw WebGL at all: checked once, on a throwaway canvas. */
function detectWebGL(): boolean {
  if (webglSupport === undefined) {
    const canvas = document.createElement("canvas");
    webglSupport =
      (canvas.getContext("webgl2") ?? canvas.getContext("webgl")) !== null;
  }
  return webglSupport;
}

const never = () => () => {};

function useWebGL(): boolean | null {
  return useSyncExternalStore(never, detectWebGL, () => null);
}

/**
 * Keeps a scene that fails after the check (a lost or refused context) from taking the page;
 * the panel then shows the table, as it does without WebGL.
 */
class SceneBoundary extends Component<
  { children: ReactNode; onError: () => void },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onError();
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
