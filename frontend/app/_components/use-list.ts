"use client";

import { useEffect, useEffectEvent, useRef, useState } from "react";
import { RunError } from "@/lib/api";

export type ListState<T> = {
  /** `error`: the last load failed; `items` still holds what an earlier load returned. */
  status: "loading" | "ready" | "error";
  items: T[];
  /** When `items` was loaded (epoch ms); null before the first load. */
  loadedAt: number | null;
};

const RECHECK_MS = 1500;

/**
 * A list from the server, loaded while `enabled` and again whenever `reloadOn` changes or
 * `refresh` is called. A load overtaken by the next one is aborted, so the list never goes back.
 *
 * `load` is always the latest one passed, but changing it does not load again: `reloadOn` does.
 * `recheck` loads once more a moment later, for a change the server records late.
 */
export function useList<T>(
  load: (signal: AbortSignal) => Promise<T[]>,
  enabled: boolean,
  reloadOn: unknown,
  recheck = false,
) {
  const [state, setState] = useState<ListState<T>>({
    status: "loading",
    items: [],
    loadedAt: null,
  });
  const [refreshes, setRefreshes] = useState(0);
  const latestLoad = useEffectEvent(load);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadOn and refreshes are not read, they are the signals to load again
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const run = () => {
      setState((s) => ({ ...s, status: "loading" }));
      latestLoad(controller.signal).then(
        (items) => setState({ status: "ready", items, loadedAt: Date.now() }),
        () => {
          if (!controller.signal.aborted) {
            setState((s) => ({ ...s, status: "error" }));
          }
        },
      );
    };
    run();
    const again = recheck ? setTimeout(run, RECHECK_MS) : undefined;
    return () => {
      clearTimeout(again);
      controller.abort();
    };
  }, [enabled, reloadOn, refreshes, recheck]);

  return { ...state, refresh: () => setRefreshes((n) => n + 1) };
}

export type ResourceState<T> = {
  /** `error`: the last load failed; `value` still holds what an earlier load returned. */
  status: "loading" | "ready" | "error";
  value: T | null;
  /** The last load was a 404: the server does not have it. */
  missing: boolean;
};

/**
 * One thing from the server, loaded while `enabled` and only when `reloadOn` (a string or number)
 * differs from what was last loaded: a panel kept mounted and shown again loads nothing, and a
 * reload keeps showing the previous value until the new one arrives. `load` is always the latest
 * one passed; whatever it depends on goes in `reloadOn`.
 */
export function useResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  enabled: boolean,
  reloadOn: string | number,
): ResourceState<T> {
  const [state, setState] = useState<ResourceState<T>>({
    status: "loading",
    value: null,
    missing: false,
  });
  const loadedFor = useRef<string | number | null>(null);
  const latestLoad = useEffectEvent(load);

  useEffect(() => {
    if (!enabled || loadedFor.current === reloadOn) return;
    const controller = new AbortController();
    setState((s) => ({ ...s, status: "loading" }));
    latestLoad(controller.signal).then(
      (value) => {
        loadedFor.current = reloadOn;
        setState({ status: "ready", value, missing: false });
      },
      (err) => {
        if (controller.signal.aborted) return;
        const missing = err instanceof RunError && err.status === 404;
        setState((s) => ({ ...s, status: "error", missing }));
      },
    );
    return () => controller.abort();
  }, [enabled, reloadOn]);

  return state;
}

/** The console's footer for a list: how many, and when they were loaded. */
export function listFooter(
  { status, items, loadedAt }: ListState<unknown>,
  noun: string,
): string {
  if (loadedAt === null) {
    const nouns = `${noun}s`;
    return status === "error"
      ? `${nouns[0].toUpperCase()}${nouns.slice(1)} not loaded`
      : `Loading ${nouns}…`;
  }
  const count = `${items.length} ${items.length === 1 ? noun : `${noun}s`}`;
  const at = new Date(loadedAt).toLocaleTimeString();
  return status === "error"
    ? `${count} · last loaded ${at} · refresh failed`
    : `${count} · loaded ${at}`;
}
