import { ClerkProvider } from "@clerk/nextjs";
import { shadcn } from "@clerk/ui/themes";
import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ApiAuth } from "./_components/api-auth";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "TraceScan",
  description: "Triage LLM app failures: cluster, diagnose, and draft issues.",
};

/** Dark only: the browser draws its own chrome, form controls and scrollbars dark too. */
export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "black",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        {/* Not `dynamic`: it reads nothing from the request, so pages still prerender their shell
            (cacheComponents). Clerk's own components draw with the design tokens (shadcn theme). */}
        <ClerkProvider
          appearance={{ theme: shadcn }}
          signInUrl="/sign-in"
          signUpUrl="/sign-up"
        >
          <ApiAuth />
          {children}
        </ClerkProvider>
      </body>
    </html>
  );
}
