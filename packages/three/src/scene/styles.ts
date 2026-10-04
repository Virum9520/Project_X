import type { CSSProperties } from "react";

/** Inline styles for in-scene HTML (labels, chips, evidence cards), so consumers need no CSS. */

export const FONT = "var(--font-geist-sans, ui-sans-serif, system-ui, sans-serif)";

export const labelStyle: CSSProperties = {
  fontFamily: FONT,
  fontSize: 12,
  lineHeight: 1.2,
  color: "#e8ecf6",
  background: "rgba(11, 16, 32, 0.72)",
  border: "1px solid rgba(155, 231, 255, 0.18)",
  borderRadius: 999,
  padding: "4px 10px",
  whiteSpace: "nowrap",
  backdropFilter: "blur(6px)",
  cursor: "pointer",
  userSelect: "none",
  transition: "opacity 300ms ease, transform 300ms ease",
};

export const groveLabelStyle: CSSProperties = {
  ...labelStyle,
  borderRadius: 14,
  padding: "8px 12px",
  minWidth: 140,
  textAlign: "left",
};

export const chipStyle: CSSProperties = {
  ...labelStyle,
  fontSize: 11,
  padding: "3px 8px",
};

export const cardStyle: CSSProperties = {
  fontFamily: FONT,
  width: 230,
  color: "#e8ecf6",
  background: "rgba(16, 22, 44, 0.86)",
  border: "1px solid rgba(155, 231, 255, 0.25)",
  borderRadius: 14,
  padding: 12,
  fontSize: 12,
  lineHeight: 1.4,
  boxShadow: "0 12px 32px rgba(0, 0, 0, 0.35)",
  backdropFilter: "blur(8px)",
  cursor: "pointer",
  textAlign: "left",
};

export const buttonReset: CSSProperties = {
  font: "inherit",
  color: "inherit",
  background: "none",
  border: "none",
  padding: 0,
  margin: 0,
  cursor: "pointer",
  textAlign: "inherit",
};
