"use client";

import { CalendarIcon } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const DATE_FORMAT = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

/** Formats a "YYYY-MM-DDTHH:mm" local value for display, or returns `fallback` when empty. */
export function formatLocal(local: string, fallback: string): string {
  if (!local) return fallback;
  return DATE_FORMAT.format(new Date(local));
}

const pad = (n: number) => String(n).padStart(2, "0");

function toDateStr(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function parseDateStr(s: string): Date {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/**
 * Date and time picker built on the themed Calendar, because the browser's native
 * datetime-local popup can't be recolored. The value has the same shape the native input
 * produced ("YYYY-MM-DDTHH:mm" in local time, or "" when unset).
 */
export function DateTimeField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [date, time] = value ? value.split("T") : ["", ""];
  const selected = date ? parseDateStr(date) : undefined;

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Popover>
        <PopoverTrigger
          id={id}
          className={cn(
            buttonVariants({ variant: "outline" }),
            "h-9 w-full justify-start font-normal",
            !value && "text-muted-foreground",
          )}
        >
          <CalendarIcon aria-hidden="true" />
          {formatLocal(value, "Select date and time")}
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto gap-0 p-0">
          <Calendar
            mode="single"
            selected={selected}
            defaultMonth={selected}
            onSelect={(d) =>
              d && onChange(`${toDateStr(d)}T${time || "00:00"}`)
            }
            autoFocus
          />
          <div className="flex items-center gap-2 border-t p-3">
            <Label htmlFor={`${id}-time`}>Time</Label>
            <Input
              id={`${id}-time`}
              type="time"
              className="h-9 [&::-webkit-calendar-picker-indicator]:hidden"
              value={time}
              disabled={!date}
              onChange={(e) => onChange(`${date}T${e.target.value}`)}
            />
            <Button
              type="button"
              variant="ghost"
              disabled={!value}
              onClick={() => onChange("")}
            >
              Clear
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
