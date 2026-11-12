import { AppShell } from "@/app/_components/app-shell";

/** The app's pages, in the shell: nav, header and the run this window streams. */
export default function AppLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
