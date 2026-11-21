import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Logo } from "../components/Brand";
import { setToken } from "../lib/api";
import { API_BASE } from "../lib/native";
import { safeNext } from "./Auth";

/** Local dev and demo test builds only (the API serves /dev/token only with
 * PLATFORM_ENV=local): sign in as a seeded demo player and go to ?next=. */
export function DevLogin() {
  const { name = "alice" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetch(`${API_BASE}/dev/token/${encodeURIComponent(name)}`, { method: "POST" })
      .then(async (r) => {
        if (!r.ok) throw new Error(r.status === 404 ? "This server has no demo players (it isn't running in local mode)." : `Server answered ${r.status}.`);
        return (await r.json()) as { access_token: string };
      })
      .then(async (d) => {
        if (cancelled) return;
        setToken(d.access_token);
        await qc.invalidateQueries();
        navigate(safeNext(params.get("next")) ?? "/", { replace: true });
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error && e.message !== "Failed to fetch" ? e.message : "Can't reach the server.");
      });
    return () => {
      cancelled = true;
    };
  }, [name, params, navigate, qc, attempt]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-5 px-6 text-center">
      <Logo size={48} />
      {error ? (
        <>
          <div className="title text-2xl">Couldn't sign in as {name}</div>
          <p className="max-w-sm text-cream/70">{error}</p>
          <p className="text-xs text-cream/40">API: {API_BASE}</p>
          <button className="btn-gold px-8" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </>
      ) : (
        <div className="title animate-pulse text-2xl">Signing in as {name}…</div>
      )}
    </div>
  );
}
