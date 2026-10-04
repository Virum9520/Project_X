"use client";

import type { CSSProperties, ReactNode } from "react";

import { useInView } from "./use-in-view";

type Props = {
  className?: string;
  delayMs?: number;
  /** Animate on page load (CSS only) instead of waiting to scroll into view. For the hero. */
  immediate?: boolean;
};

/** A heading whose words blur into focus one after another when it scrolls into view. */
export function RevealText({
  as: Tag = "h2",
  text,
  className,
  delayMs = 0,
  immediate = false,
}: Props & { as?: "h1" | "h2" | "h3" | "p" | "span"; text: string }) {
  const [ref, inView] = useInView<HTMLHeadingElement>();
  const words = text.split(" ");
  return (
    <Tag
      ref={ref}
      data-shown={inView || immediate || undefined}
      data-immediate={immediate || undefined}
      aria-label={text}
      className={className}
      style={{ "--delay": `${delayMs}ms` } as CSSProperties}
    >
      {words.map((word, i) => (
        <span key={i} aria-hidden className="reveal-word" style={{ "--i": i } as CSSProperties}>
          {word}
          {i < words.length - 1 ? " " : ""}
        </span>
      ))}
    </Tag>
  );
}

/** Any block that fades and sharpens in on scroll. */
export function RevealBlock({
  children,
  className,
  delayMs = 0,
  immediate = false,
}: Props & { children: ReactNode }) {
  const [ref, inView] = useInView<HTMLDivElement>();
  return (
    <div
      ref={ref}
      data-shown={inView || immediate || undefined}
      data-immediate={immediate || undefined}
      className={`reveal-block ${className ?? ""}`}
      style={{ "--delay": `${delayMs}ms` } as CSSProperties}
    >
      {children}
    </div>
  );
}
