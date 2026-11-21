import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { isApiError, errorMessage } from "../lib/api";
import { play } from "../lib/sound";

type Kind = "ok" | "error" | "info";
interface Toast {
  id: number;
  kind: Kind;
  text: string;
  action?: ToastAction;
}
export interface ToastAction {
  label: string;
  to: string;
}

const ToastContext = createContext<(text: string, kind?: Kind, action?: ToastAction) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Kind = "info", action?: ToastAction) => {
    const id = Date.now() + Math.random();
    if (kind === "error") play("error");
    setToasts((t) => [...t.slice(-2), { id, kind, text, action }]);
    // Give a toast with a button a little longer to be tapped.
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), action ? 7000 : 4200);
  }, []);
  const tone = {
    ok: "border-chip-green/60 text-cream",
    error: "border-chip-red/70 text-cream",
    info: "border-gold-400/50 text-cream",
  };
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div
        className="pointer-events-none fixed inset-x-0 top-3 z-50 flex flex-col items-center gap-2 px-4"
        role="status"
        aria-live="polite"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`panel animate-pop pointer-events-auto flex max-w-md items-center gap-3 border-2 px-4 py-2.5 text-sm font-medium ${tone[t.kind]}`}
          >
            <span className="flex-1">{t.text}</span>
            {t.action && (
              <Link
                to={t.action.to}
                className="shrink-0 rounded-full bg-gold-400 px-3 py-1 text-xs font-bold text-felt-950"
                onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}
              >
                {t.action.label}
              </Link>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

/** Where to go to fix a known error, so the player isn't left guessing. */
const FIX: Record<string, ToastAction> = {
  insufficient_funds: { label: "Add money", to: "/wallet" },
  out_of_play_money: { label: "Refill", to: "/wallet" },
  too_many_tables: { label: "My tables", to: "/tables" },
  username_required: { label: "Finish setup", to: "/welcome" },
  terms_required: { label: "Finish setup", to: "/welcome" },
  kyc_required: { label: "Verify", to: "/profile" },
};

/** Show an API error as a toast, with a one-tap fix when there is one. */
export function useErrorToast() {
  const toast = useToast();
  return useCallback(
    (e: unknown) => toast(errorMessage(e), "error", isApiError(e) ? FIX[e.code] : undefined),
    [toast],
  );
}
