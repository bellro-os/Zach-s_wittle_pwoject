import { ImageResponse } from "next/og";

/**
 * compbird's browser-tab icon, generated via the Next.js segment convention.
 * NO `runtime = "edge"` — Railway's Node standalone build 502s on the edge
 * runtime; next/og renders fine in Node.
 */
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          borderRadius: 8,
          backgroundColor: "#2563eb",
          color: "#ffffff",
          fontSize: 20,
          fontWeight: 700,
          fontFamily: "sans-serif",
        }}
      >
        c
      </div>
    ),
    size,
  );
}
