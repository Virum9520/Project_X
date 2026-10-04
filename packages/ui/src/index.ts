/** Skill Garden design tokens, shared by the learner and admin apps. */
export const tokens = {
  color: {
    night: "#0C0A1E",
    dusk: "#1B1640",
    moss: "#4FD1A1",
    bloom: "#FF9EC7",
    ember: "#FF8A5C",
    glow: "#FFCF70",
    wilt: "#9A8F7A",
  },
  radius: { sm: "6px", md: "12px", lg: "20px" },
} as const;

/** Clerk `appearance` for both apps, so sign-in and profile screens match the garden at night. */
export const clerkAppearance = {
  variables: {
    colorPrimary: tokens.color.moss,
    colorPrimaryForeground: tokens.color.night,
    colorBackground: tokens.color.dusk,
    colorForeground: "#F3EEFC",
    colorMutedForeground: "#B4ABCF",
    colorInput: tokens.color.night,
    colorInputForeground: "#F3EEFC",
    colorNeutral: "#F3EEFC",
    colorDanger: tokens.color.ember,
    borderRadius: tokens.radius.md,
  },
} as const;
