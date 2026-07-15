/**
 * Emits schema.org JSON-LD. A server component (no "use client") so the
 * <script> is present in the SSR HTML and crawlers read it without running JS.
 */
export function JsonLd({ schema }: { schema: object | object[] }) {
  return (
    <script
      type="application/ld+json"
      // No user input flows in here, but escape "<" defensively so a literal
      // "</script>" can never terminate the tag early.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(schema).replace(/</g, "\\u003c") }}
    />
  );
}
