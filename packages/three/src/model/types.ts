import type { Character, Dimension, PlantPart } from "@sg/contracts";

/**
 * Semantic zoom level of the garden camera: Garden → Grove → Plant → Part.
 * A plant's grove is looked up from the layout, so it is not repeated here.
 */
export type GardenFocus =
  | { level: "garden" }
  | { level: "grove"; groveId: string }
  | { level: "plant"; conceptId: string }
  | { level: "part"; conceptId: string; part: PlantPart };

export type FocusLevel = GardenFocus["level"];

/** Display model for an evidence card orbiting a plant part at Part level. */
export interface EvidenceCardData {
  id: string;
  dimension: Dimension;
  kind: "transcript" | "code" | "test";
  character: Character;
  title: string;
  /** Verbatim quote, code excerpt or test summary. Rendered as text, never as markup. */
  excerpt: string;
  occurredAt: string;
  independent: boolean;
  /** Judge uncertainty in [0, 1]. */
  uncertainty: number;
  rubricVersion: string;
}
