"use client";

import { Tabs as TabsPrimitive } from "@base-ui/react/tabs";
import { cn } from "cn";

/** The segmented look, shared with the time-window picker in the run form. */
export const SEGMENT_LIST = "flex gap-1 rounded-lg border bg-muted p-1";
export const SEGMENT_ITEM =
  "type-body cursor-pointer rounded-md px-3 py-1 text-center text-muted-foreground transition-colors select-none hover:text-foreground";

function Tabs({ className, ...props }: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn("flex flex-col", className)}
      {...props}
    />
  );
}

function TabsList({ className, ...props }: TabsPrimitive.List.Props) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(SEGMENT_LIST, className)}
      {...props}
    />
  );
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        SEGMENT_ITEM,
        "outline-none focus-visible:ring-2 focus-visible:ring-ring data-active:bg-primary data-active:text-primary-foreground data-active:hover:text-primary-foreground",
        className,
      )}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn("outline-none", className)}
      {...props}
    />
  );
}

export { Tabs, TabsList, TabsTrigger, TabsContent };
