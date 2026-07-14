"""Warm CMA worker — a long-lived localhost HTTP service that keeps the heavy
imports + AVM model resident so the Next app never pays the ~5-12s cold start
per profile/CMA request.

Zero third-party deps (Python stdlib http.server) so it adds nothing to the
engine's install footprint. The Next app calls it over 127.0.0.1 and FALLS BACK
to its existing per-request `python` spawn if this worker is down — so the
worker is a pure optimization that can never regress the app.

Endpoints (all JSON):
  GET  /healthz            -> {"ok": true, "warm": bool}
  POST /profile  {address?, parcelId?, n?, months?}   -> build_profile(...) dict
  POST /generate {address?, parcelId?, brand?, brandProfile?, agent?, comps?,
                  excluded?, months?, nComps?, allowMultiPage?, aiHygiene?}
                  -> build_cma(...) dict
                  (brandProfile = a saved tenant BrandProfile dict; when present
                   it renders the tenant's own brand, else the `brand` YAML name)

Single-threaded ON PURPOSE: build_cma / build_profile read the process-global
env var CMA_SKIP_AVM (fast-mode toggle), so serializing requests makes setting
it per-request race-free. Warm profile calls are sub-second; the rare long PDF
generate briefly serializes others, who fall back to the Next spawn pool. Run a
second instance on another port behind the same fallback if more concurrency is
ever needed.

    python worker/cma_worker.py            # PORT from CMA_WORKER_PORT (default 8765)
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote

# ── path/cwd bootstrap (mirror property_profile.py / build_cma's expectations) ──
_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(_ROOT / "scripts"), str(_ROOT / "src")):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)
os.chdir(_ROOT)

# Where build_cma writes generated reports (out_dir default = _PROJECT_ROOT/outputs;
# on Railway the engine entrypoint symlinks /app/outputs onto the data volume).
# GET /outputs/<name> serves from here so the APP service — which lives on a
# SEPARATE Railway volume and cannot read this dir directly — can stream the PDF
# it just asked us to generate. CMA_OUTPUTS_DIR honored for parity with the app.
_OUTPUTS_DIR = Path(os.environ.get("CMA_OUTPUTS_DIR", "").strip() or (_ROOT / "outputs"))

PORT = int(os.environ.get("CMA_WORKER_PORT", "8765"))

# ── deployment knobs (all additive; defaults reproduce the original behavior) ──
# Bind host. Default 127.0.0.1 keeps today's localhost-only behavior; set to
# "0.0.0.0" to expose the worker inside a container / shared engine service.
HOST = os.environ.get("CMA_WORKER_HOST", "127.0.0.1")
# Optional bearer token. When set, POST /profile and /generate require an
# "Authorization: Bearer <token>" header. When unset (default), no auth — the
# original localhost-only behavior is unchanged.
TOKEN = (os.environ.get("CMA_WORKER_TOKEN") or "").strip()
# Per-request hard timeout in seconds. 0 (default) = off, i.e. today's behavior
# where a request runs to completion. When > 0, a single request that exceeds
# the budget returns a 504-style JSON error so one stuck call can't hang the
# (single-threaded) server forever.
try:
    REQ_TIMEOUT = float(os.environ.get("CMA_WORKER_REQ_TIMEOUT", "0") or "0")
except ValueError:
    REQ_TIMEOUT = 0.0

_WARM = {"ok": False}


def _warm() -> None:
    """Pay every cold cost ONCE at boot: import the engine + load the AVM
    regressor (~5s sklearn import + ~7s joblib load) so requests are warm."""
    global _WARM
    # Import the engine cores. property_profile sets CMA_SKIP_AVM=1 via setdefault
    # on import — we manage it explicitly per-request below, so clear it now.
    import build_cma  # noqa: F401  (warms its module graph)
    from build_cma import build_cma as _bc
    from build_cma import build_preview as _bpv
    from property_profile import build_profile as _bp
    import mls_bot.analytics.avm as _avm

    os.environ.pop("CMA_SKIP_AVM", None)
    try:
        _avm._load_model()  # cache the regressor in-process (idempotent, ~7s once)
    except Exception as e:  # the AVM is optional; profile fast-mode skips it anyway
        print(f"[cma_worker] AVM warm failed (non-fatal): {e}", file=sys.stderr, flush=True)

    _WARM = {"ok": True, "build_cma": _bc, "build_profile": _bp, "build_preview": _bpv}


def _select_pool(body: dict) -> None:
    """Point the comp pool at a per-request parquet (compbird's supplemental pool)
    when the request carries ``listingsParquet``, else the MLS default. Safe on the
    single-threaded worker — every request sets it from its OWN body, so it can
    never leak to a request (e.g. the host's Ratifyly CMA) that didn't ask for it.
    See cma_compset._fast_listings_connection; mirrors the CMA_SKIP_AVM pattern."""
    os.environ["CMA_LISTINGS_PARQUET"] = (body.get("listingsParquet") or "").strip()


def _profile(body: dict) -> dict:
    # build_profile manages CMA_SKIP_AVM itself based on aiHygiene/fullValuation.
    # Full-accuracy mode (aiHygiene=True — set by the app's CMA profile route)
    # runs the AVM + Haiku comp-hygiene so the displayed estimate equals the
    # generated CMA's value. fullValuation=True (compbird's profile route sends
    # it always) forces the AVM on even with hygiene off — /preview's exact
    # posture — so the first-paint profile number equals the tuned preview and
    # the PDF for the same aiHygiene flag. Both absent (default) keeps the fast
    # interactive path, so existing callers are byte-identical and AI spend
    # stays opt-in.
    _select_pool(body)
    return _WARM["build_profile"](
        (body.get("address") or "").strip() or None,
        (body.get("parcelId") or "").strip() or None,
        n_comps=int(body.get("n") or 6),
        months_back=int(body.get("months") or 24),
        ai_hygiene=bool(body.get("aiHygiene", False)),
        full_valuation=bool(body.get("fullValuation", False)),
        subject_overrides=body.get("subjectOverrides") or None,
    )


def _generate(body: dict) -> dict:
    # Full CMA / PDF — AVM ON (env cleared). Mirrors the generate route's RUNNER.
    os.environ.pop("CMA_SKIP_AVM", None)
    _select_pool(body)
    r = _WARM["build_cma"](
        address=(body.get("address") or "").strip() or None,
        parcel_id=(body.get("parcelId") or "").strip() or None,
        brand_name=body.get("brand") or "ratifyly",
        brand_profile=body.get("brandProfile") or None,
        agent_name=body.get("agent") or None,
        comp_overrides=body.get("comps") or None,
        excluded_comps=body.get("excluded") or None,
        n_comps=int(body.get("nComps") or 6),
        months_back=int(body.get("months") or 24),
        allow_multi_page=bool(body.get("allowMultiPage")),
        ai_hygiene=bool(body.get("aiHygiene", True)),  # default ON; deterministic w/o key
        subject_sqft=int(body["subjectSqft"]) if body.get("subjectSqft") else None,
        subject_overrides=body.get("subjectOverrides") or None,
        report_config=body.get("reportConfig") or None,
    )
    out = {
        "ok": True,
        "subject_address": r.subject_address,
        "estimated_value": r.estimated_value,
        "value_low": r.value_low,
        "value_high": r.value_high,
        "comp_count": r.comp_count,
        "pages": r.pages,
        "elapsed_seconds": r.elapsed_seconds,
        "autofit_attempts": r.autofit_attempts,
        "html_path": str(r.html_path),
        "pdf_path": str(r.pdf_path),
    }
    # Blind-ensemble surface — additive keys appended only under
    # CMA_BLIND_ENSEMBLE=1 (compbird's engine env) so the unset (Ratifyly)
    # response stays byte-identical. Mirrors /preview's valuation.ai_blind.
    if os.environ.get("CMA_BLIND_ENSEMBLE", "").strip() == "1":
        out["ai_blind"] = getattr(r, "ai_blind", None)
        out["ai_ensemble"] = bool(getattr(r, "ai_ensemble", False))
        # Measured confidence tier ("high"|"standard") — engine-computed, so
        # the report and the studio tell the same honest story.
        out["confidence_tier"] = getattr(r, "confidence_tier", None)
    return out


def _preview(body: dict) -> dict:
    # Interactive comp set + valuation, NO PDF — runs the SAME prepare_comps +
    # _estimate_value pipeline as /generate (via build_preview) so the on-screen
    # estimate equals the downloaded CMA's value. build_preview manages CMA_SKIP_AVM
    # itself per ai_hygiene (default ON = full parity with the PDF). The studio sends
    # `forced` (pinned-in addresses) and `excluded`; these map to comp overrides.
    _select_pool(body)
    return _WARM["build_preview"](
        address=(body.get("address") or "").strip() or None,
        parcel_id=(body.get("parcelId") or "").strip() or None,
        comp_overrides=body.get("forced") or None,
        excluded_comps=body.get("excluded") or None,
        n_comps=int(body.get("nComps") or 6),
        months_back=int(body.get("months") or 24),
        ai_hygiene=bool(body.get("aiHygiene", True)),
        subject_overrides=body.get("subjectOverrides") or None,
        report_config=body.get("reportConfig") or None,
    )


class _RequestTimeout(Exception):
    """Raised when a handler exceeds CMA_WORKER_REQ_TIMEOUT."""


def _run_with_timeout(fn, body: dict) -> dict:
    """Run `fn(body)` with an optional wall-clock budget.

    When REQ_TIMEOUT is 0 (default) this is a plain call — byte-identical to the
    original behavior. When set, the work runs on a daemon thread we *join* with
    a timeout; if it doesn't finish in time we raise _RequestTimeout so the
    caller can return a 504-style error.

    Note (single-threaded server): the worker handles one request at a time, so
    on timeout we can't truly kill the in-flight CPU work (Python has no safe
    thread-cancel). The runaway thread is left as a daemon (won't block exit);
    the *next* request will still queue behind it. This is a best-effort guard
    to surface a timely error to the client, not a hard preemption. For true
    isolation, run multiple worker instances behind the Next fallback pool.
    """
    if REQ_TIMEOUT <= 0:
        return fn(body)

    result: dict = {}
    error: list = []

    def _target():
        try:
            result["value"] = fn(body)
        except BaseException as e:  # propagate to the caller's except handler
            error.append(e)

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(REQ_TIMEOUT)
    if t.is_alive():
        raise _RequestTimeout(f"request exceeded {REQ_TIMEOUT:g}s budget")
    if error:
        raise error[0]
    return result["value"]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet the default per-request stderr noise
        pass

    def _authorized(self) -> bool:
        """True when no token is configured (default) or the request carries the
        correct "Authorization: Bearer <token>" header."""
        if not TOKEN:
            return True
        auth = (self.headers.get("Authorization") or "").strip()
        prefix = "Bearer "
        if not auth.startswith(prefix):
            return False
        # Constant-time compare to avoid leaking the token via timing.
        import hmac

        return hmac.compare_digest(auth[len(prefix):].strip(), TOKEN)

    def _send(self, code: int, obj: dict) -> None:
        payload = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_output(self) -> None:
        """Stream a generated report PDF by basename. Token-gated (same bearer as
        the POST endpoints) so a 0.0.0.0-bound engine on a shared network can't
        leak reports; basename-only, .pdf-only, CMA_-namespaced, traversal-proof.
        The app's /api/compbird/pdf route proxies here on a local-file miss."""
        if not self._authorized():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        name = unquote(self.path[len("/outputs/"):].split("?", 1)[0])
        if (
            not name
            or len(name) > 255
            or "/" in name
            or "\\" in name
            or ".." in name
            or not name.lower().endswith(".pdf")
            or not name.startswith("CMA_")
        ):
            return self._send(400, {"ok": False, "error": "invalid name"})
        try:
            data = (_OUTPUTS_DIR / name).read_bytes()
        except FileNotFoundError:
            return self._send(404, {"ok": False, "error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"ok": False, "error": str(e)})
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'inline; filename="{name}"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/healthz"):
            return self._send(200, {"ok": True, "warm": _WARM["ok"]})
        if self.path.startswith("/outputs/"):
            return self._serve_output()
        self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        # Bearer-token gate (no-op when CMA_WORKER_TOKEN is unset → today's behavior).
        if not self._authorized():
            return self._send(401, {"ok": False, "error": "unauthorized"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._send(400, {"ok": False, "error": "invalid JSON body"})
        try:
            if self.path.startswith("/profile"):
                return self._send(200, _run_with_timeout(_profile, body))
            if self.path.startswith("/preview"):
                return self._send(200, _run_with_timeout(_preview, body))
            if self.path.startswith("/generate"):
                return self._send(200, _run_with_timeout(_generate, body))
            self._send(404, {"ok": False, "error": "not found"})
        except _RequestTimeout as e:
            # 504-style: surface a timely gateway-timeout error to the client.
            self._send(504, {"ok": False, "error": str(e), "timeout": True})
        except Exception as e:
            self._send(
                200,
                {"ok": False, "error": str(e), "traceback": traceback.format_exc()},
            )


def main() -> int:
    print(f"[cma_worker] warming (sklearn + AVM model)…", flush=True)
    _warm()
    # HOST defaults to 127.0.0.1 (localhost-only, today's behavior); set
    # CMA_WORKER_HOST=0.0.0.0 to serve a shared engine inside a container.
    # allow_reuse_address=False: on Windows the default lets a SECOND worker
    # bind the same port and split traffic nondeterministically (observed
    # live: a flagged and an unflagged worker double-bound on 8765 serving
    # different valuations). A duplicate must fail loudly instead.
    class _ExclusiveHTTPServer(HTTPServer):
        allow_reuse_address = False
        # ADDITIVE (Railway private networking): http.server binds IPv4-only
        # (AF_INET) by default, but Railway's <service>.railway.internal mesh is
        # IPv6-ONLY — a 0.0.0.0 bind is unreachable there. When CMA_WORKER_HOST
        # is an IPv6 literal (e.g. "::"), flip to AF_INET6. On Linux "::"
        # accepts BOTH families (dual-stack, bindv6only=0 default), so it is a
        # strict superset of 0.0.0.0. IPv4 hosts (the default 127.0.0.1, or
        # 0.0.0.0 in compose) behave byte-identically to before.
        address_family = socket.AF_INET6 if ":" in HOST else HTTPServer.address_family
    srv = _ExclusiveHTTPServer((HOST, PORT), Handler)
    _auth = "token-required" if TOKEN else "open"
    _to = f"{REQ_TIMEOUT:g}s" if REQ_TIMEOUT > 0 else "off"
    print(
        f"[cma_worker] ready on {HOST}:{PORT} (auth={_auth}, req-timeout={_to})",
        flush=True,
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
