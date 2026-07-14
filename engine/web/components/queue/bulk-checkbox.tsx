"use client";

interface Props {
  parcelId: string;
  county: string;
  owner: string;
  siteAddr: string;
}

/** Bulk-select checkbox. Has an `onClick` that stops propagation so
 * clicking the box doesn't also toggle the row's `<details>` expansion.
 * Must be a Client Component because event handlers can't live on
 * Server Component elements. */
export function BulkCheckbox({ parcelId, county, owner, siteAddr }: Props) {
  return (
    <input
      type="checkbox"
      className="bulk-select size-4 cursor-pointer"
      data-parcel-id={parcelId}
      data-county={county}
      data-owner={owner}
      data-addr={siteAddr}
      onClick={(e) => e.stopPropagation()}
      onChange={() =>
        document.dispatchEvent(new Event("change", { bubbles: true }))
      }
    />
  );
}
