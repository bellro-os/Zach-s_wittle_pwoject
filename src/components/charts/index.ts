/**
 * Dependency-free, dark-safe inline-SVG chart primitives for the
 * "Ink & Emerald" graphite surfaces. All are pure presentational
 * (server-component friendly — no hooks, no "use client").
 *
 * Colors flow through CSS vars (var(--primary), the positive/negative/
 * muted-foreground tokens) and currentColor so they read correctly on
 * the ink-900/800 cards. Round all displayed numbers.
 */
export { Sparkline } from "./Sparkline";
export type { SparklineProps } from "./Sparkline";

export { TrendBadge } from "./TrendBadge";
export type { TrendBadgeProps } from "./TrendBadge";

export { RadialGauge } from "./RadialGauge";
export type { RadialGaugeProps } from "./RadialGauge";

export { MiniBars } from "./MiniBars";
export type { MiniBarItem, MiniBarsProps } from "./MiniBars";

export { GeoScatter } from "./GeoScatter";
export type { GeoPoint, GeoScatterProps } from "./GeoScatter";

export { DonutChart } from "./DonutChart";
export type { DonutSegment, DonutChartProps } from "./DonutChart";
