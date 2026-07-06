"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/compbird/ui";
import {
  generateReport,
  pdfUrl,
  startSubscription,
  CompbirdApiError,
} from "@/lib/compbird/api";
import type { SubjectOverrides, ReportConfig } from "@/lib/cma/overrides";

/**
 * Renders the full PDF dossier on demand. Live rendering needs the Python
 * engine + Chromium; when that isn't reachable we never crash — we surface a
 * short toast and leave the on-screen report intact.
 */
export function ReportActions({
  address,
  parcelId,
  isSample,
  excluded,
  forced,
  subjectOverrides,
  reportConfig,
  evidence = true,
}: {
  address?: string;
  parcelId?: string;
  isSample: boolean;
  /** Comp keys excluded in the studio — carried into the rendered PDF. */
  excluded?: string[];
  /** Addresses pinned IN as comps — carried into the rendered PDF. */
  forced?: string[];
  /** Agent what-if subject overrides (sqft/condition) — carried into the PDF. */
  subjectOverrides?: SubjectOverrides;
  /** Report composition / exec-summary override — carried into the PDF. */
  reportConfig?: ReportConfig;
  /**
   * False when the viewer is evidence-locked (FREE plan on a live report):
   * downloads are Pro, so the download button becomes the upgrade affordance
   * instead of firing a doomed 2-minute render.
   */
  evidence?: boolean;
}) {
  const [generating, setGenerating] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const router = useRouter();

  // Same navigate-on-success / toast-on-error contract as the account menu.
  function onUpgrade() {
    if (upgrading) return;
    setUpgrading(true);
    startSubscription().catch((e) => {
      toast.error(e instanceof Error ? e.message : "Could not start checkout.");
      setUpgrading(false);
    });
  }

  async function onGenerate() {
    // The sample dossier has no live subject to render — never fire a ~2-min
    // engine spawn for it (the button is disabled, this is belt-and-suspenders).
    if (generating || isSample) return;
    setGenerating(true);
    const t = toast.loading("Rendering full report…");
    try {
      // Send the same tuning the user sees on screen so the PDF matches the studio.
      const res = await generateReport({
        address,
        parcelId,
        excluded,
        forced,
        subjectOverrides,
        reportConfig,
      });
      if (res.ok && res.pdfName) {
        toast.success(
          res.pages ? `Report ready · ${res.pages} pages` : "Report ready",
          { id: t },
        );
        window.open(pdfUrl(res.pdfName), "_blank", "noopener,noreferrer");
        // Re-render the server page so any plan-derived header state stays
        // truthful in-session (e.g. right after a subscription change).
        router.refresh();
      } else {
        toast.error(res.error || "Report engine is offline right now.", { id: t });
      }
    } catch (err) {
      // Downloads are Pro: 403 {code:"pro_required"} = evidence-locked plan →
      // offer to subscribe; 402 = legacy metered-quota path, kept for safety;
      // 401 = session lapsed → send back through the free-account wall.
      const proWalled =
        err instanceof CompbirdApiError &&
        (err.status === 402 || (err.status === 403 && err.code === "pro_required"));
      if (proWalled) {
        toast.error(
          err.message ||
            (err.status === 402
              ? "You've used all your report downloads this month."
              : "Report downloads are part of Pro."),
          {
            id: t,
            duration: 10000,
            action: {
              label: "Upgrade to Pro · $20/mo",
              onClick: () => {
                void startSubscription().catch((e) =>
                  toast.error(e instanceof Error ? e.message : "Could not start checkout."),
                );
              },
            },
          },
        );
      } else if (err instanceof CompbirdApiError && err.status === 401) {
        toast.error("Create a free account to download reports.", {
          id: t,
          action: {
            label: "Create account",
            onClick: () => {
              window.location.href = "/join?redirect=%2Fcomps";
            },
          },
        });
      } else if (err instanceof CompbirdApiError && err.rateLimited) {
        toast.error("Too many requests — please slow down.", { id: t });
      } else {
        toast.error("Couldn't reach the report engine.", { id: t });
      }
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-3">
        {evidence ? (
          <Button onClick={onGenerate} disabled={generating || isSample} arrow={!generating && !isSample}>
            {generating ? "Rendering…" : "Download full report (PDF)"}
          </Button>
        ) : (
          <Button onClick={onUpgrade} disabled={upgrading} arrow={!upgrading}>
            {upgrading ? "Opening checkout…" : "Unlock report downloads · Pro"}
          </Button>
        )}
        <span className="text-xs text-muted-foreground">
          {!evidence
            ? "Branded, multi-page PDFs are part of Pro · $20/mo · cancel anytime"
            : isSample
              ? "This is a sample — search a real address above to generate a full report"
              : "Branded, multi-page · ready to send to a client"}
        </span>
      </div>
    </div>
  );
}
