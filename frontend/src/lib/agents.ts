// The twelve TerraTrace AI specialist agents, in execution order.
// Descriptions are short, honest summaries of what each agent actually checks.

import {
  Building2,
  Droplets,
  Flame,
  Mountain,
  Pickaxe,
  Radar,
  Snowflake,
  Trees,
  Waves,
  Wheat,
  type LucideIcon,
} from "lucide-react";

export interface AgentMeta {
  id: string;
  ordinal: number;
  /** Short display name for the sequence list. */
  shortName: string;
  /** One plain-language line: what this agent checks. */
  checks: string;
  icon: LucideIcon;
}

export const AGENTS: AgentMeta[] = [
  {
    id: "flood",
    ordinal: 1,
    shortName: "Flood & Inundation",
    checks: "Standing water from the before/after water masks.",
    icon: Waves,
  },
  {
    id: "wetlands",
    ordinal: 2,
    shortName: "Wetlands & Water Bodies",
    checks: "Water-surface change against wetland ceilings.",
    icon: Droplets,
  },
  {
    id: "forest",
    ordinal: 3,
    shortName: "Forest & Deforestation",
    checks: "Backscatter loss consistent with canopy removal.",
    icon: Trees,
  },
  {
    id: "wildfire",
    ordinal: 4,
    shortName: "Wildfire & Burned Land",
    checks: "Burn scars in the radar change mask.",
    icon: Flame,
  },
  {
    id: "deformation",
    ordinal: 5,
    shortName: "Ground Deformation",
    checks: "Displacement products (InSAR), not intensity data.",
    icon: Mountain,
  },
  {
    id: "glacier",
    ordinal: 6,
    shortName: "Glacier & Cryosphere",
    checks: "Snow/ice extent and glacier surface change.",
    icon: Snowflake,
  },
  {
    id: "landslide",
    ordinal: 7,
    shortName: "Landslide & Slope",
    checks: "Slope-disturbance signature on steep terrain.",
    icon: Mountain,
  },
  {
    id: "agriculture",
    ordinal: 8,
    shortName: "Agriculture & Farming",
    checks: "Field-scale cropland surface change.",
    icon: Wheat,
  },
  {
    id: "urban",
    ordinal: 9,
    shortName: "Urban Growth",
    checks: "New hard surfaces near built-up areas.",
    icon: Building2,
  },
  {
    id: "mining",
    ordinal: 10,
    shortName: "Mining & Land Disturbance",
    checks: "Radars visible as compact high-reflectivity pits.",
    icon: Pickaxe,
  },
  {
    id: "coastal",
    ordinal: 11,
    shortName: "Coastal & Shoreline",
    checks: "Shoreline retreat or advance at the water edge.",
    icon: Waves,
  },
  {
    id: "unknown_change",
    ordinal: 12,
    shortName: "Unknown-Change Discovery",
    checks: "Leftover change regions nobody claimed.",
    icon: Radar,
  },
];

export function agentMeta(id: string): AgentMeta | undefined {
  return AGENTS.find((a) => a.id === id);
}

/** Human category for a finding category enum. */
export const CATEGORY_LABELS: Record<string, string> = {
  FLOOD_INUNDATION: "Flood & inundation",
  WETLAND_WATER: "Wetland & water change",
  FOREST_LOSS: "Forest loss",
  WILDFIRE_BURNED: "Burned land",
  GROUND_DEFORMATION: "Ground deformation",
  GLACIER_CRYOSPHERE: "Glacier & cryosphere change",
  LANDSLIDE_SLOPE: "Landslide & slope disturbance",
  AGRICULTURE: "Agriculture change",
  URBAN_INFRASTRUCTURE: "Urban growth & infrastructure",
  MINING_DISTURBANCE: "Mining disturbance",
  COASTAL_SHORELINE: "Coastal & shoreline change",
  UNCASSIFIED_CHANGE: "Unclassified change",
};

export function categoryLabel(category: string | null | undefined): string {
  if (!category) return "Change";
  return CATEGORY_LABELS[category] ?? category.toLowerCase().replace(/_/g, " ");
}
