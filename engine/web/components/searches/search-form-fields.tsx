/** Shared form fields for create + edit pages. Pure form rendering — submit
 * is handled by a server action passed in via the parent <form action=...>. */

import type { SearchCriteria } from "@/lib/data/saved-searches";

const INPUT_CLS =
  "w-full h-9 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm focus:outline-none focus:ring-2 focus:ring-(--color-ring)";

const COMMON_DISTRICTS = [
  "Auburn",
  "Blacksburg",
  "Christiansburg",
  "Eastern Montgomery",
  "Floyd County",
  "Giles",
  "Pulaski County",
  "Radford",
];

const CLASSES = [
  { value: "RE_1", label: "Residential" },
  { value: "MF_2", label: "Multi-family" },
  { value: "FM_5", label: "Farm" },
  { value: "LD_3", label: "Land" },
  { value: "CM_4", label: "Commercial" },
];

const STATUSES = ["Active", "Pending"];

export function SearchFormFields({
  defaults,
  clients,
  centerLabel,
}: {
  defaults: {
    name?: string;
    description?: string;
    clientId?: string;
    criteria?: SearchCriteria;
  };
  clients: Array<{ id: string; displayId: string; name: string }>;
  centerLabel?: string | null;
}) {
  const c = defaults.criteria ?? {};
  const checked = (list: string[] | undefined, val: string, fallback = false) =>
    list ? list.includes(val) : fallback;

  return (
    <div className="space-y-5">
      <Section title="Basics">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Name" required>
            <input
              name="name"
              required
              defaultValue={defaults.name ?? ""}
              placeholder="Miriam — dental office sites"
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Attach to client (optional)">
            <select
              name="clientId"
              defaultValue={defaults.clientId ?? ""}
              className={INPUT_CLS}
            >
              <option value="">— standalone watchlist —</option>
              {clients.map((cl) => (
                <option key={cl.id} value={cl.id}>
                  {cl.name} ({cl.displayId})
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Description (optional)">
          <textarea
            name="description"
            defaultValue={defaults.description ?? ""}
            rows={2}
            placeholder="Why this search matters — surfaced on the detail page."
            className={INPUT_CLS}
          />
        </Field>
      </Section>

      <Section title="Price + size">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Field label="Min price">
            <input
              type="number"
              name="price_min"
              defaultValue={c.price_min ?? ""}
              placeholder="0"
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Max price">
            <input
              type="number"
              name="price_max"
              defaultValue={c.price_max ?? ""}
              placeholder="400000"
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Min sqft">
            <input
              type="number"
              name="sqft_min"
              defaultValue={c.sqft_min ?? ""}
              placeholder="1800"
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Max sqft">
            <input
              type="number"
              name="sqft_max"
              defaultValue={c.sqft_max ?? ""}
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Min beds">
            <input
              type="number"
              name="beds_min"
              defaultValue={c.beds_min ?? ""}
              placeholder="3"
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Min full baths">
            <input
              type="number"
              name="baths_min"
              defaultValue={c.baths_min ?? ""}
              placeholder="2"
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Min acres">
            <input
              type="number"
              step="0.1"
              name="acres_min"
              defaultValue={c.acres_min ?? ""}
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Max acres">
            <input
              type="number"
              step="0.1"
              name="acres_max"
              defaultValue={c.acres_max ?? ""}
              className={INPUT_CLS}
            />
          </Field>
        </div>
      </Section>

      <Section title="Location">
        <Field label="School districts">
          <div className="flex flex-wrap gap-2 text-xs">
            {COMMON_DISTRICTS.map((d) => (
              <label
                key={d}
                className="inline-flex items-center gap-1 rounded border border-(--color-border) px-2 py-1 cursor-pointer hover:bg-(--color-accent)/40"
              >
                <input
                  type="checkbox"
                  name="school_districts"
                  value={d}
                  defaultChecked={checked(c.school_districts, d)}
                />
                {d}
              </label>
            ))}
          </div>
        </Field>
        <Field label="Cities (comma-separated, optional)">
          <input
            type="text"
            name="cities"
            defaultValue={c.cities?.join(", ") ?? ""}
            placeholder="Blacksburg, Christiansburg"
            className={INPUT_CLS}
          />
        </Field>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2 border-t border-(--color-border)">
          <div className="md:col-span-2">
            <Field label="Center point (address or 'lat, lng')">
              <input
                type="text"
                name="center_address"
                defaultValue={centerLabel ?? ""}
                placeholder="Auburn HS, Riner VA  or  37.085, -80.387"
                className={INPUT_CLS}
              />
              <p className="text-[10px] text-(--color-muted-foreground) mt-1">
                Geocoded via OpenStreetMap. Paste &quot;lat, lng&quot; to skip
                the lookup. Mountain drives can exceed the straight-line
                radius — pad accordingly.
              </p>
            </Field>
          </div>
          <Field label="Radius (mi)">
            <input
              type="number"
              step="0.5"
              name="radius_mi"
              defaultValue={c.radius_mi ?? ""}
              placeholder="10"
              className={INPUT_CLS}
            />
          </Field>
        </div>
        {/* Hidden lat/lng fields for edit flow — server action will overwrite
            them if center_address is set to something new. */}
        <input
          type="hidden"
          name="center_lat"
          defaultValue={c.center_lat ?? ""}
        />
        <input
          type="hidden"
          name="center_lng"
          defaultValue={c.center_lng ?? ""}
        />
      </Section>

      <Section title="Property type + status">
        <Field label="Classes (default: residential)">
          <div className="flex flex-wrap gap-2 text-xs">
            {CLASSES.map((cls) => (
              <label
                key={cls.value}
                className="inline-flex items-center gap-1 rounded border border-(--color-border) px-2 py-1 cursor-pointer hover:bg-(--color-accent)/40"
              >
                <input
                  type="checkbox"
                  name="classes"
                  value={cls.value}
                  defaultChecked={checked(c.classes, cls.value, cls.value === "RE_1")}
                />
                {cls.label}
              </label>
            ))}
          </div>
        </Field>
        <Field label="Status">
          <div className="flex gap-2 text-xs">
            {STATUSES.map((s) => (
              <label
                key={s}
                className="inline-flex items-center gap-1 rounded border border-(--color-border) px-2 py-1 cursor-pointer hover:bg-(--color-accent)/40"
              >
                <input
                  type="checkbox"
                  name="statuses"
                  value={s}
                  defaultChecked={checked(c.statuses, s, s === "Active")}
                />
                {s}
              </label>
            ))}
          </div>
        </Field>
        <Field label="Listed within last N days (optional)">
          <input
            type="number"
            name="listed_within_days"
            defaultValue={c.listed_within_days ?? ""}
            placeholder="30"
            className="form-input w-40"
          />
        </Field>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-(--color-muted-foreground)">
        {title}
      </h2>
      {children}
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium">
        {label}
        {required && <span className="text-(--color-destructive)"> *</span>}
      </span>
      {children}
    </label>
  );
}
