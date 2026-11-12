import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// The pages someone signed out can reach: the ways in. Listed this way round so a page added
// later is behind the sign-in until it is named here.
const isPublicPage = createRouteMatcher(["/sign-in(.*)", "/sign-up(.*)"]);

// Signed out on any other page is a redirect to /sign-in. This is the optimistic check: what
// protects the data is the backend, which verifies the session token on every /api call.
export default clerkMiddleware(
  async (auth, req) => {
    if (!isPublicPage(req)) await auth.protect();
  },
  { signInUrl: "/sign-in", signUpUrl: "/sign-up" },
);

export const config = {
  // Pages only: not Next's own files, static files, or /api, which the rewrite in next.config.ts
  // hands to the backend as it is (the backend answers 401 there, which a fetch can read, where a
  // redirect to /sign-in it could not).
  matcher: [
    "/((?!_next|api/|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
  ],
};
