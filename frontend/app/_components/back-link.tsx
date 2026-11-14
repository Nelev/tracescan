import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** The way back to a list from one of its pages ("All runs", "All traces"). */
export function BackLink({
  href,
  children,
}: {
  href: string;
  children: string;
}) {
  return (
    <Link
      href={href}
      className={cn(buttonVariants({ variant: "ghost" }), "-ml-2.5 w-fit")}
    >
      <ArrowLeft aria-hidden="true" />
      {children}
    </Link>
  );
}
