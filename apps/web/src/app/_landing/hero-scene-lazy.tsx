"use client";

import dynamic from "next/dynamic";
import { Component, type ReactNode } from "react";

const HeroScene = dynamic(() => import("./hero-scene"), { ssr: false });

/** Without WebGL the hero keeps its gradient backdrop instead of crashing the page. */
class WebGLBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export function LazyHeroScene() {
  return (
    <WebGLBoundary>
      <HeroScene />
    </WebGLBoundary>
  );
}
