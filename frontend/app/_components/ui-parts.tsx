"use client";

import type { BaseComponentProps } from "@json-render/react";
import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * The components that draw a server-written UI spec, one per entry of lib/ui-catalog.ts. They are
 * ours, not @json-render/shadcn's: that package cannot be imported a component at a time, and
 * these follow the design system (the type scale and the tokens in globals.css). A prop the model
 * leaves out arrives as undefined or null, and an unknown value falls back to a default. Class
 * names are written out in full, so Tailwind can see them.
 */

type Maybe<T> = T | null | undefined;

const GAP = {
  none: "gap-0",
  sm: "gap-2",
  md: "gap-4",
  lg: "gap-6",
  xl: "gap-8",
} as const;
const ITEMS = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  stretch: "items-stretch",
} as const;
const JUSTIFY = {
  start: "justify-start",
  center: "justify-center",
  end: "justify-end",
  between: "justify-between",
  around: "justify-around",
} as const;
const COLUMNS = [
  "sm:grid-cols-1",
  "sm:grid-cols-2",
  "sm:grid-cols-3",
  "sm:grid-cols-4",
  "sm:grid-cols-5",
  "sm:grid-cols-6",
] as const;

/** The entry for `key` in `map`, else `fallback`; not `map[key]`, which would answer to "constructor". */
function pick<T>(map: Record<string, T>, key: Maybe<string>, fallback: T): T {
  return key != null && Object.hasOwn(map, key) ? map[key] : fallback;
}

export function UiStack({
  props,
  children,
}: BaseComponentProps<{
  direction?: Maybe<string>;
  gap?: Maybe<string>;
  align?: Maybe<string>;
  justify?: Maybe<string>;
}>) {
  return (
    <div
      className={cn(
        "flex",
        props.direction === "horizontal" ? "flex-row flex-wrap" : "flex-col",
        pick(GAP, props.gap, GAP.md),
        pick(ITEMS, props.align, ""),
        pick(JUSTIFY, props.justify, ""),
      )}
    >
      {children}
    </div>
  );
}

export function UiGrid({
  props,
  children,
}: BaseComponentProps<{ columns?: Maybe<number>; gap?: Maybe<string> }>) {
  const columns = Math.min(Math.max(Math.round(props.columns ?? 1), 1), 6);
  return (
    <div
      className={cn(
        "grid grid-cols-1",
        COLUMNS[columns - 1],
        pick(GAP, props.gap, GAP.md),
      )}
    >
      {children}
    </div>
  );
}

export function UiCard({
  props,
  children,
}: BaseComponentProps<{ title?: Maybe<string>; description?: Maybe<string> }>) {
  return (
    <Card>
      {(props.title || props.description) && (
        <CardHeader>
          {props.title && <CardTitle>{props.title}</CardTitle>}
          {props.description && (
            <CardDescription>{props.description}</CardDescription>
          )}
        </CardHeader>
      )}
      <CardContent className="flex flex-col gap-4">{children}</CardContent>
    </Card>
  );
}

export function UiSeparator({
  props,
}: BaseComponentProps<{ orientation?: Maybe<string> }>) {
  return props.orientation === "vertical" ? (
    <hr
      aria-orientation="vertical"
      className="w-px self-stretch border-0 bg-border"
    />
  ) : (
    <hr className="border-border" />
  );
}

export function UiCollapsible({
  props,
  children,
}: BaseComponentProps<{ title: string; defaultOpen?: Maybe<boolean> }>) {
  return (
    <details
      open={props.defaultOpen ?? false}
      className="rounded-lg border px-3 py-2"
    >
      <summary className="type-h3 cursor-pointer">{props.title}</summary>
      <div className="flex flex-col gap-3 pt-3">{children}</div>
    </details>
  );
}

// The run output already has an h2 above the messages, so the model's levels step down by one.
const HEADING = {
  h1: { Tag: "h3", className: "type-h2" },
  h2: { Tag: "h3", className: "type-h2" },
  h3: { Tag: "h4", className: "type-h3" },
  h4: { Tag: "h5", className: "type-h4" },
} as const;

export function UiHeading({
  props,
}: BaseComponentProps<{ text: string; level?: Maybe<string> }>) {
  const { Tag, className } = pick(HEADING, props.level, HEADING.h3);
  return <Tag className={className}>{props.text}</Tag>;
}

const TEXT = {
  body: "type-body",
  caption: "type-body text-muted-foreground",
  muted: "type-body text-muted-foreground",
  lead: "type-h2 font-normal",
  code: "type-body font-mono",
} as const;

export function UiText({
  props,
}: BaseComponentProps<{ text: string; variant?: Maybe<string> }>) {
  return (
    <p
      className={cn(
        "whitespace-pre-wrap [overflow-wrap:anywhere]",
        pick(TEXT, props.variant, TEXT.body),
      )}
    >
      {props.text}
    </p>
  );
}

const BADGE = {
  default: "border-transparent bg-primary text-primary-foreground",
  secondary: "border-transparent bg-secondary text-secondary-foreground",
  destructive: "border-destructive/40 bg-destructive/10 text-destructive",
  outline: "text-foreground",
} as const;

export function UiBadge({
  props,
}: BaseComponentProps<{ text: string; variant?: Maybe<string> }>) {
  return (
    <span
      className={cn(
        "type-body inline-flex w-fit items-center border px-2.5 py-0.5",
        pick(BADGE, props.variant, BADGE.default),
      )}
    >
      {props.text}
    </span>
  );
}

// What kind of finding it is is said in words for a screen reader and shown by an icon, not by
// color alone. The page is content, not a message to the reader, so it has no role="alert".
const ALERT = {
  error: { Icon: CircleAlert, word: "Error", destructive: true, icon: "" },
  warning: {
    Icon: TriangleAlert,
    word: "Warning",
    destructive: false,
    icon: "text-ring",
  },
  success: {
    Icon: CircleCheck,
    word: "Success",
    destructive: false,
    icon: "text-success",
  },
  info: { Icon: Info, word: "Note", destructive: false, icon: "text-ring" },
} as const;

export function UiAlert({
  props,
}: BaseComponentProps<{
  title: string;
  message?: Maybe<string>;
  type?: Maybe<string>;
}>) {
  const kind = pick(ALERT, props.type, ALERT.info);
  const { Icon } = kind;
  return (
    <Alert role="note" variant={kind.destructive ? "destructive" : "default"}>
      <Icon aria-hidden="true" className={kind.icon} />
      <AlertTitle className="type-body font-medium">
        <span className="sr-only">{kind.word}: </span>
        {props.title}
      </AlertTitle>
      {props.message && (
        <AlertDescription className="type-body">
          {props.message}
        </AlertDescription>
      )}
    </Alert>
  );
}

const cell = (value: unknown) => (value == null ? "" : String(value));

export function UiTable({
  props,
}: BaseComponentProps<{
  columns: unknown[];
  rows: unknown[][];
  caption?: Maybe<string>;
}>) {
  return (
    <div className="relative overflow-x-auto rounded-lg border">
      <table className="type-body w-full border-collapse text-left">
        {props.caption && (
          <caption className="type-body p-3 text-left text-muted-foreground">
            {props.caption}
          </caption>
        )}
        <thead className="border-b border-rule bg-muted">
          <tr>
            {props.columns.map((column, i) => (
              <th
                // biome-ignore lint/suspicious/noArrayIndexKey: a fixed header row, never reordered
                key={i}
                scope="col"
                className="type-body px-3 py-2 font-medium text-muted-foreground"
              >
                {cell(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.rows.map((row, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: rows have no id and are never reordered
            <tr key={i} className="border-b last:border-b-0">
              {(Array.isArray(row) ? row : [row]).map((value, j) => (
                <td
                  // biome-ignore lint/suspicious/noArrayIndexKey: cells have no id and are never reordered
                  key={j}
                  className="px-3 py-2 align-top [overflow-wrap:anywhere]"
                >
                  {cell(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
