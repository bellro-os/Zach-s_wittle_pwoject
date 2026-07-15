import { ImageResponse } from "next/og";

/**
 * compbird's social-share card (og:image / twitter:image), generated at request
 * time via the Next.js segment convention — no binary asset to maintain, always
 * on-brand with the blue + light "Paper" surface. Site-wide default (compbird is
 * a standalone app rooted at /), overridable by a deeper segment.
 *
 * NOTE: NO `runtime = "edge"` — Railway serves the Node standalone build, on
 * which the edge runtime 502s ("Application failed to respond"). next/og renders
 * fine in the Node runtime, so we let it default to Node.
 */
export const alt =
  "compbird — appraisal-grade comparables and live market reports in seconds";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "72px 80px",
          backgroundColor: "#f7f8fa",
          backgroundImage:
            "radial-gradient(52rem 52rem at 88% -10%, rgba(37,99,235,0.14), transparent 60%)",
          fontFamily: "sans-serif",
        }}
      >
        {/* wordmark */}
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              backgroundColor: "#2563eb",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#ffffff",
              fontSize: 26,
              fontWeight: 700,
            }}
          >
            c
          </div>
          <div style={{ fontSize: 40, fontWeight: 700, color: "#111726" }}>
            compbird
          </div>
        </div>

        {/* headline */}
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <div
            style={{
              // Satori requires display:flex on any element with >1 child.
              display: "flex",
              flexWrap: "wrap",
              fontSize: 74,
              fontWeight: 700,
              lineHeight: 1.05,
              letterSpacing: "-0.02em",
              color: "#111726",
              maxWidth: 980,
            }}
          >
            <span>A bird&rsquo;s-eye view of what every home is&nbsp;</span>
            <span style={{ color: "#1d4ed8" }}>really worth.</span>
          </div>
          <div style={{ fontSize: 30, color: "#4b5563", maxWidth: 900 }}>
            Appraisal-grade comparables and live neighborhood market reports — in
            seconds.
          </div>
        </div>

        {/* stat strip */}
        <div
          style={{
            display: "flex",
            gap: 56,
            borderTop: "1px solid #e2e5ea",
            paddingTop: 34,
          }}
        >
          {[
            ["Statewide", "assessor parcels"],
            ["~2s", "to six comps"],
            ["6 methods", "cross-checked"],
          ].map(([k, v]) => (
            <div key={v} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div style={{ fontSize: 34, fontWeight: 700, color: "#111726" }}>{k}</div>
              <div style={{ fontSize: 22, color: "#6b7280" }}>{v}</div>
            </div>
          ))}
        </div>
      </div>
    ),
    size,
  );
}
