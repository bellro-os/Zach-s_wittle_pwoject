"use client";

import { useRouter } from "next/navigation";

export function CitySelect({
  cities,
  value,
  daysBack,
  minPrice,
}: {
  cities: string[];
  value: string;
  daysBack: number;
  minPrice: number;
}) {
  const router = useRouter();
  return (
    <select
      value={value}
      onChange={(e) => {
        const params = new URLSearchParams();
        if (e.target.value) params.set("city", e.target.value);
        params.set("days", String(daysBack));
        if (minPrice > 0) params.set("min_price", String(minPrice));
        router.push(`/expired?${params.toString()}`);
      }}
      className="h-8 rounded-md border border-(--color-input) bg-(--color-background) px-2 text-sm"
    >
      <option value="">All cities</option>
      {cities.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}
