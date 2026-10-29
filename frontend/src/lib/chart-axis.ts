/** Shared Recharts axis styling and MW tick formatting. */
export const axis = (muted: string, border: string) => ({
  tick: { fill: muted, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: border },
})

/** 12000 -> "12k", 1750 -> "1.75k", 550 -> "550": distinct labels even on narrow ranges. */
export const kTicks = (v: number) =>
  Math.abs(v) < 1000 ? `${Math.round(v)}` : `${Number((v / 1000).toFixed(2))}k`
