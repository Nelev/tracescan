"use client";

import { Billboard, CameraControls, Line } from "@react-three/drei";
import { Canvas, type ThreeEvent, useFrame } from "@react-three/fiber";
import {
  type ComponentRef,
  type RefObject,
  useEffect,
  useRef,
  useState,
} from "react";
import { Box3, DoubleSide, Vector3 } from "three";
import { ConvexGeometry } from "three/examples/jsm/geometries/ConvexGeometry.js";
import {
  type ClusterLabel,
  clusterBounds,
  clusterOutline,
  type MapPoint,
  markRadius,
  type Outline,
  STAGE_MARK,
  type Vec3,
} from "@/lib/cluster-map";
import { cn } from "@/lib/utils";

/** Where the floor sits: just under the lowest a point can be (the map is in [-1, 1]). */
const FLOOR = -1.1;
const FLOOR_SIZE = 2.2;
const START: Vec3 = [3.4, 2.3, 3.4];
/** The turn the map makes when it opens, in radians, and how slowly. */
const INTRO_TURN = 0.7;
const INTRO_SMOOTH_S = 1.1;
const SMOOTH_S = 0.25;
// camera-controls' ACTION values: rotate with the left button or one finger, dolly with the
// wheel or two fingers, nothing else (no pan: the map always turns about its centre or a cluster).
const MOUSE = { left: 1, middle: 16, right: 0, wheel: 16 } as const;
const TOUCH = { one: 64, two: 1024, three: 0 } as const;

type Ctrl = ComponentRef<typeof CameraControls>;

/**
 * The cluster map's 3D scene: one flat mark per point, always facing the camera, over a hairline
 * floor it drops a line to, fading with distance; the selected cluster outlined. Labels and the
 * hover label are DOM over the canvas, placed each frame. Loaded on demand, client only. Colors
 * are the design tokens, read from the page and read again when the system theme flips.
 */
export default function ClusterMap3D({
  points,
  labels,
  selected,
  describe,
  onPick,
  onPickCluster,
  flight,
  resetSignal,
}: {
  points: MapPoint[];
  labels: ClusterLabel[];
  /** The selected cluster: its marks in ink and outlined, the others muted. */
  selected: string | null;
  /** The hover label's text for a point. */
  describe: (point: MapPoint) => string;
  /** A mark was clicked (not dragged), or the empty space (null). */
  onPick: (index: number | null) => void;
  /** A cluster label was clicked (select) or double-clicked (fly to it). */
  onPickCluster: (clusterId: string, fly: boolean) => void;
  /** The cluster to fly to; a new object for each flight, so the same cluster can fly again. */
  flight: { clusterId: string } | null;
  /** Bumped to put the camera back where it started. */
  resetSignal: number;
}) {
  const ink = useInk();
  const controls = useRef<Ctrl>(null);
  const labelEls = useRef(new Map<string, HTMLElement>());
  const hoverEl = useRef<HTMLDivElement>(null);
  const hoverLabel = useRef<HTMLSpanElement>(null);
  const hoverLeader = useRef<HTMLSpanElement>(null);
  // Index into `points` under the pointer: only the scene needs it.
  const [hovered, setHovered] = useState<number | null>(null);

  useEffect(() => {
    if (resetSignal > 0) void controls.current?.reset(true);
  }, [resetSignal]);

  useEffect(() => {
    const bounds = flight && clusterBounds(points, flight.clusterId);
    if (!bounds || !controls.current) return;
    const box = new Box3(
      new Vector3(...bounds.min),
      new Vector3(...bounds.max),
    );
    void controls.current.fitToBox(box, true, {
      paddingTop: 0.2,
      paddingBottom: 0.2,
      paddingLeft: 0.2,
      paddingRight: 0.2,
    });
  }, [flight, points]);

  const hoveredPoint = hovered === null ? null : (points[hovered] ?? null);

  return (
    <div
      className={cn(
        "relative h-full overflow-hidden",
        hovered !== null && "cursor-pointer",
      )}
    >
      <Canvas
        flat // no tone mapping: the tokens' colors exactly
        frameloop="demand"
        dpr={[1, 2]}
        camera={{ position: START, fov: 38 }}
        gl={{ antialias: true, alpha: true }}
        onPointerMissed={() => onPick(null)}
        aria-hidden="true"
      >
        {/* Far marks fade toward the panel's own surface: a depth cue that keeps one ink. */}
        <fog attach="fog" args={[ink.card, 4.2, 9]} />
        <CameraControls
          ref={controls}
          makeDefault
          minDistance={0.8}
          maxDistance={9}
          smoothTime={SMOOTH_S}
          mouseButtons={MOUSE}
          touches={TOUCH}
        />
        <Intro controls={controls} />
        <gridHelper
          args={[FLOOR_SIZE, 4, ink.border, ink.border]}
          position={[0, FLOOR, 0]}
        />
        <DropLines points={points} selected={selected} ink={ink} />
        {points.map((point, index) => (
          <Mark
            key={`${point.cluster_id}:${point.trace_ids[0]}`}
            point={point}
            index={index}
            ink={ink}
            dim={selected !== null && point.cluster_id !== selected}
            hovered={hovered === index}
            onHover={setHovered}
            onPick={onPick}
          />
        ))}
        {selected !== null && (
          <ClusterOutline
            outline={clusterOutline(points, selected)}
            ink={ink}
          />
        )}
        <Tracker
          labels={labels}
          labelEls={labelEls.current}
          hovered={hoveredPoint}
          hover={{ box: hoverEl, label: hoverLabel, leader: hoverLeader }}
        />
      </Canvas>

      {/* DOM over the canvas, placed by Tracker each frame drawn. The cluster labels can be
          clicked (select) and double-clicked (fly); the panel's buttons are the keyboard path,
          so these stay out of the tab order. */}
      <div className="pointer-events-none absolute inset-0">
        {labels.map((label) => (
          <button
            key={label.cluster_id}
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            ref={(el) => {
              if (el) labelEls.current.set(label.cluster_id, el);
              else labelEls.current.delete(label.cluster_id);
            }}
            onClick={() => onPickCluster(label.cluster_id, false)}
            onDoubleClick={() => onPickCluster(label.cluster_id, true)}
            className={cn(
              "type-h4 pointer-events-auto invisible absolute top-0 left-0 cursor-pointer px-1 font-mono normal-case transition-colors select-none hover:text-foreground",
              label.cluster_id === selected && "text-foreground",
            )}
          >
            {label.cluster_id}
          </button>
        ))}
        {/* The hover label and its leader, placed apart by Tracker: the leader stands on the
            mark, the label is kept inside the frame. */}
        <div
          ref={hoverEl}
          aria-hidden="true"
          className="invisible absolute inset-0"
        >
          {hoveredPoint && (
            <>
              <span
                ref={hoverLabel}
                className="type-body absolute top-0 left-0 w-max max-w-72 rounded-md border surface-raised px-2 py-0.5 text-foreground"
              >
                {describe(hoveredPoint)}
              </span>
              <span
                ref={hoverLeader}
                className="absolute top-0 left-0 h-4 w-px bg-foreground"
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const projected = new Vector3();
const HOVER_GAP = 10; // between the mark and the leader's foot
const LEADER = 16; // the leader's length, as its h-4
const EDGE_PAD = 4;
const clamp = (v: number, lo: number, hi: number) =>
  Math.min(Math.max(v, lo), Math.max(lo, hi));

function toScreen(
  x: number,
  y: number,
  z: number,
  camera: Parameters<Parameters<typeof useFrame>[0]>[0]["camera"],
  size: { width: number; height: number },
): { left: number; top: number; inFront: boolean } {
  projected.set(x, y, z).project(camera);
  return {
    left: ((projected.x + 1) / 2) * size.width,
    top: ((1 - projected.y) / 2) * size.height,
    inFront: projected.z < 1,
  };
}

type HoverRefs = {
  box: RefObject<HTMLDivElement | null>;
  label: RefObject<HTMLSpanElement | null>;
  leader: RefObject<HTMLSpanElement | null>;
};

/** Each frame drawn, puts the hover label on its mark and every cluster label over its centre. */
function Tracker({
  labels,
  labelEls,
  hovered,
  hover,
}: {
  labels: ClusterLabel[];
  labelEls: Map<string, HTMLElement>;
  hovered: MapPoint | null;
  hover: HoverRefs;
}) {
  useFrame(({ camera, size }) => {
    // The hover label first: it reads its own size, which is cheap before any style is written.
    const box = hover.box.current;
    const label = hover.label.current;
    const leader = hover.leader.current;
    if (box) {
      if (!hovered || !label || !leader) {
        box.style.visibility = "hidden";
      } else {
        const at = toScreen(hovered.x, hovered.y, hovered.z, camera, size);
        // The leader rises from just above the mark; the label sits on top of it, starting a
        // little left of it and pushed back inside the frame when it would cross an edge.
        const head = at.top - HOVER_GAP - LEADER;
        const left = clamp(
          at.left - 12,
          EDGE_PAD,
          size.width - label.offsetWidth - EDGE_PAD,
        );
        const top = Math.max(EDGE_PAD, head - label.offsetHeight);
        leader.style.transform = `translate(${at.left}px, ${head}px)`;
        label.style.transform = `translate(${left}px, ${top}px)`;
        box.style.visibility = at.inFront ? "visible" : "hidden";
      }
    }
    for (const cluster of labels) {
      const el = labelEls.get(cluster.cluster_id);
      if (!el) continue;
      const at = toScreen(cluster.x, cluster.y, cluster.z, camera, size);
      el.style.transform = `translate(${at.left}px, ${at.top}px) translate(-50%, -170%)`;
      el.style.visibility = at.inFront ? "visible" : "hidden";
    }
  });
  return null;
}

/** One slow quarter-turn when the map opens, so it reads as 3D; none with reduced motion. */
function Intro({ controls }: { controls: RefObject<Ctrl | null> }) {
  useEffect(() => {
    const ctrl = controls.current;
    if (!ctrl) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    void ctrl.rotate(-INTRO_TURN, 0, false);
    ctrl.smoothTime = INTRO_SMOOTH_S;
    void ctrl.rotate(INTRO_TURN, 0, true).then(() => {
      ctrl.smoothTime = SMOOTH_S;
    });
  }, [controls]);
  return null;
}

type Ink = {
  foreground: string;
  muted: string;
  border: string;
  card: string;
};

/**
 * Every mark's drop line to the floor, as two batches of segments (the selected cluster's or all,
 * and the dimmed rest): where each mark stands, to judge depth by.
 */
function DropLines({
  points,
  selected,
  ink,
}: {
  points: MapPoint[];
  selected: string | null;
  ink: Ink;
}) {
  const segments = (dim: boolean) =>
    new Float32Array(
      points
        .filter((p) => (selected !== null && p.cluster_id !== selected) === dim)
        .flatMap((p) => [p.x, p.y, p.z, p.x, FLOOR, p.z]),
    );
  return (
    <>
      {[false, true].map((dim) => (
        <lineSegments key={`${dim}:${selected}`}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              args={[segments(dim), 3]}
            />
          </bufferGeometry>
          <lineBasicMaterial color={dim ? ink.border : ink.muted} />
        </lineSegments>
      ))}
    </>
  );
}

function ClusterOutline({
  outline,
  ink,
}: {
  outline: Outline | null;
  ink: Ink;
}) {
  if (!outline) return null;
  if (outline.kind === "spokes") {
    return (
      <>
        {outline.ends.map((end) => (
          <Line
            key={end.join()}
            points={[outline.center, end]}
            color={ink.foreground}
            lineWidth={1}
            transparent
            opacity={0.5}
          />
        ))}
      </>
    );
  }
  return <Hull vertices={outline.vertices} ink={ink} />;
}

function Hull({ vertices, ink }: { vertices: Vec3[]; ink: Ink }) {
  const geometry = new ConvexGeometry(vertices.map((v) => new Vector3(...v)));
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <group>
      <mesh geometry={geometry}>
        <meshBasicMaterial
          color={ink.foreground}
          transparent
          opacity={0.06}
          depthWrite={false}
          side={DoubleSide}
        />
      </mesh>
      <lineSegments>
        <edgesGeometry args={[geometry]} />
        <lineBasicMaterial color={ink.foreground} transparent opacity={0.35} />
      </lineSegments>
    </group>
  );
}

function Mark({
  point,
  index,
  ink,
  dim,
  hovered,
  onHover,
  onPick,
}: {
  point: MapPoint;
  index: number;
  ink: Ink;
  dim: boolean;
  hovered: boolean;
  onHover: (index: number | null) => void;
  onPick: (index: number) => void;
}) {
  const r = markRadius(point.trace_ids.length);
  const mark = STAGE_MARK[point.stage];
  return (
    <group>
      {/* The drop line's foot on the floor (the lines themselves are drawn by DropLines). */}
      <mesh
        position={[point.x, FLOOR + 0.001, point.z]}
        rotation-x={-Math.PI / 2}
      >
        <circleGeometry args={[r * 0.5, 16]} />
        <meshBasicMaterial color={dim ? ink.border : ink.muted} />
      </mesh>
      <Billboard position={[point.x, point.y, point.z]}>
        <mesh>
          {mark === "dot" ? (
            <circleGeometry args={[r, 32]} />
          ) : mark === "square" ? (
            <planeGeometry args={[r * 1.7, r * 1.7]} />
          ) : (
            <ringGeometry args={[r * 0.6, r, 32]} />
          )}
          <meshBasicMaterial
            color={dim ? ink.muted : ink.foreground}
            transparent={dim}
            opacity={dim ? 0.35 : 1}
            depthWrite={!dim}
          />
        </mesh>
        {hovered && (
          <mesh>
            <ringGeometry args={[r * 1.35, r * 1.55, 40]} />
            <meshBasicMaterial color={ink.foreground} />
          </mesh>
        )}
        {/* A larger, invisible target, so a small mark is easy to point at. */}
        {/* biome-ignore lint/a11y/noStaticElementInteractions: a three.js mesh, not DOM; the panel's cluster buttons and table are the keyboard path */}
        <mesh
          onPointerOver={(e: ThreeEvent<PointerEvent>) => {
            e.stopPropagation();
            onHover(index);
          }}
          onPointerOut={() => onHover(null)}
          onClick={(e: ThreeEvent<MouseEvent>) => {
            if (e.delta > 4) return; // the end of a drag, not a click
            e.stopPropagation();
            onPick(index);
          }}
        >
          <circleGeometry args={[Math.max(r * 1.6, 0.06), 16]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      </Billboard>
    </group>
  );
}

let inkCache: Ink | null = null;

/**
 * The design tokens the scene draws with. The app is dark only, so they never change once the
 * page has loaded: read them once (the scene only renders in the browser).
 */
function useInk(): Ink {
  inkCache ??= {
    foreground: token("--foreground"),
    muted: token("--muted-foreground"),
    border: token("--border"),
    card: token("--card"),
  };
  return inkCache;
}

/**
 * A CSS color token as `rgb(...)`. The tokens are oklch, which three.js cannot parse, so the
 * browser paints one pixel with it and the pixel is read back. Some tokens are translucent (the
 * glass card, the hairline border), so the pixel is first painted with the opaque page
 * background and the token composited over it: the color it shows on the page, not its raw hue.
 */
function token(name: string): string {
  const style = getComputedStyle(document.documentElement);
  const value = style.getPropertyValue(name).trim();
  const page = style.getPropertyValue("--background").trim();
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return "#808080";
  context.fillStyle = "#808080";
  context.fillStyle = page;
  context.fillRect(0, 0, 1, 1);
  context.fillStyle = value;
  context.fillRect(0, 0, 1, 1);
  const [r, g, b] = context.getImageData(0, 0, 1, 1).data;
  return `rgb(${r}, ${g}, ${b})`;
}
