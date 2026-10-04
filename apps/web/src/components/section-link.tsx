"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { MouseEvent, ReactNode } from "react";

/**
 * Link to a landing-page section. On the landing page it scrolls there without writing the hash
 * into the URL, so a reload starts from the top again; from other pages it navigates to `/#id`.
 */
export function SectionLink({
  id,
  className,
  children,
}: {
  id: string;
  className?: string;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    const target = document.getElementById(id);
    if (pathname !== "/" || !target) return;
    event.preventDefault();
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  return (
    <Link href={{ pathname: "/", hash: id }} className={className} onClick={onClick}>
      {children}
    </Link>
  );
}
