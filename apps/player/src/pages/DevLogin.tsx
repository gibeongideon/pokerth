import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { setToken } from "../lib/api";

/** Local dev only (not in production builds): sign in as a seeded demo player
 * and go to ?next=. Used for screenshots and quick manual testing. */
export function DevLogin() {
  const { name = "alice" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const once = useRef(false);
  useEffect(() => {
    if (once.current) return;
    once.current = true;
    fetch(`/api/dev/token/${name}`, { method: "POST" })
      .then((r) => r.json())
      .then(async (d: { access_token: string }) => {
        setToken(d.access_token);
        await qc.invalidateQueries();
        navigate(params.get("next") ?? "/", { replace: true });
      });
  }, [name, params, navigate, qc]);
  return <div className="title p-10 text-center text-2xl">Signing in as {name}…</div>;
}
