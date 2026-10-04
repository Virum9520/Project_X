/** Skill Garden design tokens, shared by the learner and admin apps. */
export const tokens = {
  color: {
    night: "#0B1020",
    dusk: "#1A2340",
    moss: "#3FAE7A",
    bloom: "#F4B8D4",
    ember: "#F2A65A",
    glow: "#9BE7FF",
    wilt: "#8A7F6A",
  },
  radius: { sm: "6px", md: "12px", lg: "20px" },
} as const;

/** Clerk `appearance` for both apps, so sign-in and profile screens match the garden at night. */
export const clerkAppearance = {
  variables: {
    colorPrimary: tokens.color.moss,
    colorPrimaryForeground: tokens.color.night,
    colorBackground: tokens.color.dusk,
    colorForeground: "#E8ECF6",
    colorMutedForeground: "#A9B2C9",
    colorInput: tokens.color.night,
    colorInputForeground: "#E8ECF6",
    colorNeutral: "#E8ECF6",
    colorDanger: tokens.color.ember,
    borderRadius: tokens.radius.md,
  },
} as const;
