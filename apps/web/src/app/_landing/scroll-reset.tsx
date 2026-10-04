"use client";

import { useEffect } from "react";

/**
 * The landing page always opens at the top (its intro plays there). Browsers otherwise restore
 * the previous scroll position on reload. Arriving at `/#section` from another page still works.
 */
export function ScrollReset() {
  useEffect(() => {
    const previous = history.scrollRestoration;
    history.scrollRestoration = "manual";
    if (!location.hash) window.scrollTo({ top: 0, behavior: "instant" });
    return () => {
      history.scrollRestoration = previous;
    };
  }, []);
  return null;
}
