import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, call } from "./api";
import type { Invite, Me, TableView, Tier, Wallet } from "./types";

export function useMe() {
  return useQuery({
    queryKey: ["me"],
    queryFn: () => call<Me>(api.GET("/me")),
    retry: false,
    staleTime: 30_000,
  });
}

export function useWallet(enabled = true) {
  return useQuery({
    queryKey: ["wallet"],
    queryFn: () => call<Wallet>(api.GET("/wallet")),
    enabled,
    refetchInterval: 15_000,
  });
}

export function useTiers() {
  return useQuery({
    queryKey: ["tiers"],
    queryFn: () => call<Tier[]>(api.GET("/lobby/tiers")),
    staleTime: 60_000,
  });
}

export function useInvites(enabled = true) {
  return useQuery({
    queryKey: ["invites"],
    queryFn: () => call<Invite[]>(api.GET("/invites")),
    enabled,
    refetchInterval: 20_000,
  });
}

/** Tables I'm seated at that haven't finished. ``fast`` polls quicker (My tables page). */
export function useMyTables(enabled = true, fast = false) {
  return useQuery({
    queryKey: ["my-tables"],
    queryFn: () => call<TableView[]>(api.GET("/tables/mine")),
    enabled,
    refetchInterval: fast ? 4000 : 15_000,
  });
}

/** Whole seconds until ``deadline`` (ISO), ticking every second. */
export function useSecondsLeft(deadline: string | null | undefined): number | null {
  const compute = () =>
    deadline ? Math.max(0, Math.round((new Date(deadline).getTime() - Date.now()) / 1000)) : null;
  const [left, setLeft] = useState(compute);
  useEffect(() => {
    setLeft(compute());
    if (!deadline) return;
    const id = setInterval(() => setLeft(compute()), 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deadline]);
  return left;
}
