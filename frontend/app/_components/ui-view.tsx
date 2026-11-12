"use client";

import type { Spec } from "@json-render/core";
import { defineRegistry, JSONUIProvider, Renderer } from "@json-render/react";
import { shadcnComponents } from "@json-render/shadcn";
import { memo, useEffect, useMemo } from "react";
import type { UiMessage } from "@/lib/events";
import { catalog, checkUi } from "@/lib/ui-catalog";
import {
  UiAlert,
  UiBadge,
  UiCard,
  UiCollapsible,
  UiGrid,
  UiHeading,
  UiSeparator,
  UiStack,
  UiTable,
  UiText,
} from "./ui-parts";

// The whole catalog is drawable: the package's own components for every type, except the ten we
// draw ourselves (ui-parts.tsx), which follow the design system. The package's are imported as a
// set, so all of them load with this chunk, which is itself loaded only when the console is shown.
const { registry } = defineRegistry(catalog, {
  components: {
    ...shadcnComponents,
    Stack: UiStack,
    Grid: UiGrid,
    Card: UiCard,
    Separator: UiSeparator,
    Collapsible: UiCollapsible,
    Table: UiTable,
    Heading: UiHeading,
    Text: UiText,
    Badge: UiBadge,
    Alert: UiAlert,
  },
});

/**
 * One message of the server, drawn. The spec was written by a model, so it is checked against the
 * catalog first. The page only says that the layout is invalid; where and why (a path and a code,
 * never a value) goes to the browser console.
 */
const Message = memo(function Message({ message }: { message: UiMessage }) {
  const checked = useMemo(() => checkUi(message.spec), [message.spec]);
  useEffect(() => {
    if (!checked.ok) {
      console.error(
        `the ${message.event} message's layout is invalid:`,
        checked.issues,
      );
    }
  }, [checked, message.event]);

  if (!checked.ok) {
    return (
      <p role="alert" className="type-body text-destructive">
        A message could not be displayed: its layout is invalid.
      </p>
    );
  }
  return (
    <Renderer spec={message.spec as unknown as Spec} registry={registry} />
  );
});

/** The messages the server sent, each as the UI its model laid out. */
export function UiMessages({ messages }: { messages: UiMessage[] }) {
  return (
    <JSONUIProvider registry={registry}>
      <ol
        role="log"
        aria-label="Messages from the run"
        className="flex flex-col gap-(--message-gap) p-4"
      >
        {messages.map((message) => (
          <li
            key={message.id}
            className="ai-context rounded-r-lg py-2 pr-2 pl-3 motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1 motion-safe:duration-300"
          >
            <Message message={message} />
          </li>
        ))}
      </ol>
    </JSONUIProvider>
  );
}
