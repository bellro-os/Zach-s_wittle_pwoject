"use client";

import { cn } from "@/lib/utils";

/** Shared input class for compact form rows. */
const INPUT_CLS =
  "w-full h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm focus:outline-none focus:ring-2 focus:ring-(--color-ring)";

interface Defaults {
  id?: string;
  name?: string;
  phone?: string;
  altPhone?: string;
  email?: string;
  source?: string;
  category?: string;
  tags?: string;
  anniversary?: Date | string | null;
  birthday?: Date | string | null;
  parcelId?: string;
  county?: string;
  referredById?: string;
  notes?: string;
}

interface Props {
  defaults?: Defaults;
  /** Other clients for the "Referred by" picker (id, displayId, name). */
  allClients?: { id: string; displayId: string; name: string }[];
  /** Hide the "Their parcel" + "County" fields (e.g. when those values are
   * being supplied programmatically by a hidden input from a convert flow). */
  hideParcelFields?: boolean;
}

function toISODate(v: Date | string | null | undefined): string {
  if (!v) return "";
  if (typeof v === "string") return v.slice(0, 10);
  return v.toISOString().slice(0, 10);
}

/** All editable client fields, laid out for use inside Add and Edit forms.
 * The parent `<form>` should be either a plain `<form action={…}>` or an
 * `<ActionForm>` — this component renders only the input markup. */
export function ClientFormFields({
  defaults = {},
  allClients = [],
  hideParcelFields,
}: Props) {
  return (
    <div className="space-y-2 text-sm">
      {defaults.id && (
        <input type="hidden" name="id" value={defaults.id} />
      )}

      <div className="grid grid-cols-2 gap-2">
        <Field label="Full name *">
          <input
            name="name"
            required
            defaultValue={defaults.name ?? ""}
            className={INPUT_CLS}
          />
        </Field>
        <Field label="Tier">
          <select
            name="category"
            defaultValue={defaults.category ?? ""}
            className={INPUT_CLS}
          >
            <option value="">—</option>
            <option value="A">A — VIP</option>
            <option value="B">B — Active</option>
            <option value="C">C — Cold</option>
          </select>
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Field label="Phone">
          <input
            name="phone"
            defaultValue={defaults.phone ?? ""}
            className={INPUT_CLS}
          />
        </Field>
        <Field label="Alt phone">
          <input
            name="altPhone"
            defaultValue={defaults.altPhone ?? ""}
            className={INPUT_CLS}
          />
        </Field>
      </div>

      <Field label="Email">
        <input
          type="email"
          name="email"
          defaultValue={defaults.email ?? ""}
          className={INPUT_CLS}
        />
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Field label="Source">
          <select
            name="source"
            defaultValue={defaults.source ?? ""}
            className={INPUT_CLS}
          >
            <option value="">— Source —</option>
            <option value="referral">Referral</option>
            <option value="past_client">Past client</option>
            <option value="SOI">Sphere of influence</option>
            <option value="cold">Cold prospect</option>
            <option value="website">Website</option>
            <option value="open_house">Open house</option>
            <option value="other">Other</option>
          </select>
        </Field>
        <Field label="Referred by">
          <select
            name="referredById"
            defaultValue={defaults.referredById ?? ""}
            className={INPUT_CLS}
          >
            <option value="">— None —</option>
            {allClients
              .filter((c) => c.id !== defaults.id)
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
          </select>
        </Field>
      </div>

      <Field label="Tags (comma-separated)">
        <input
          name="tags"
          placeholder="VIP, dinner-list, blacksburg"
          defaultValue={defaults.tags ?? ""}
          className={INPUT_CLS}
        />
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Field label="Anniversary (closing date)">
          <input
            type="date"
            name="anniversary"
            defaultValue={toISODate(defaults.anniversary)}
            className={INPUT_CLS}
          />
        </Field>
        <Field label="Birthday">
          <input
            type="date"
            name="birthday"
            defaultValue={toISODate(defaults.birthday)}
            className={INPUT_CLS}
          />
        </Field>
      </div>

      {!hideParcelFields && (
        <div className="grid grid-cols-2 gap-2">
          <Field label="Parcel ID (their home)">
            <input
              name="parcelId"
              defaultValue={defaults.parcelId ?? ""}
              placeholder="e.g. 089A 3 27"
              className={cn(INPUT_CLS, "font-mono")}
            />
          </Field>
          <Field label="County">
            <input
              name="county"
              defaultValue={defaults.county ?? ""}
              placeholder="MONTGOMERY"
              className={INPUT_CLS}
            />
          </Field>
        </div>
      )}

      <Field label="Notes">
        <textarea
          name="notes"
          rows={3}
          defaultValue={defaults.notes ?? ""}
          className={cn(INPUT_CLS, "h-auto py-2")}
        />
      </Field>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-wider font-semibold text-(--color-muted-foreground) block mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}
