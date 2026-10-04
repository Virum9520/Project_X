import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Optimistic gate only: pages and actions re-check the session (see `src/lib/session.ts`).
const isPublic = createRouteMatcher([
  "/",
  "/healthz",
  "/sign-in(.*)",
  "/sign-up(.*)",
  // Mock-data dashboard preview; the page itself 404s in production.
  ...(process.env.NODE_ENV === "production" ? [] : ["/dev/garden"]),
]);

export default clerkMiddleware(
  async (auth, request) => {
    if (!isPublic(request)) await auth.protect();
  },
  { signInUrl: "/sign-in", signUpUrl: "/sign-up" },
);

export const config = {
  matcher: [
    // Skip Next internals and static files unless they appear in search params.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
