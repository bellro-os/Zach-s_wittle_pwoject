import { NextResponse } from "next/server";
import { listBrands } from "@/lib/brands";

export const dynamic = "force-dynamic";

export async function GET() {
  const brands = await listBrands();
  return NextResponse.json({ brands });
}
