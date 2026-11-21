import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Spinner } from "./components/bits";
import { Logo } from "./components/Brand";
import { NativeBridge } from "./components/NativeBridge";
import { Shell } from "./components/Shell";
import { useMe } from "./lib/hooks";
import { AuthCallback, Login, Welcome, rememberRef, rememberReturn } from "./pages/Auth";
import { Lobby } from "./pages/Lobby";
import { Profile } from "./pages/Profile";
import { Friends, JoinByCode, Organize } from "./pages/Social";
import { InviteLanding } from "./pages/Invite";
import { MyTables } from "./pages/MyTables";
import { DepositReturn, WalletPage } from "./pages/Wallet";
import { DevLogin } from "./pages/DevLogin";
import { DEMO_PLAYER, DEV_TOOLS } from "./lib/native";

// The table (PixiJS + game protocol) is the heaviest screen: load it on demand.
const TableRoom = lazy(() => import("./pages/TableRoom").then((m) => ({ default: m.TableRoom })));

function Protected({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isLoading) return <Spinner />;
  // Offline or server trouble is not "signed out": offer a retry instead of the login screen.
  const status = (me.error as { status?: number } | null)?.status;
  if (!me.data && me.error && status !== 401 && status !== 403) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <Logo size={44} />
        <div className="title text-2xl">Can't reach Draely</div>
        <p className="max-w-xs text-cream/65">Check your connection and try again.</p>
        <button className="btn-gold px-8" onClick={() => void me.refetch()}>
          Try again
        </button>
      </div>
    );
  }
  if (!me.data) {
    // Test build: no login screen, sign straight in as the demo player.
    if (DEMO_PLAYER) return <Navigate to={`/dev-login/${DEMO_PLAYER}?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
    rememberReturn(location.pathname + location.search);
    rememberRef(new URLSearchParams(location.search).get("ref")); // e.g. /?ref=CODE
    return <Navigate to="/login" replace />;
  }
  if (!me.data.username || !me.data.terms_accepted) return <Navigate to="/welcome" replace />;
  return <Shell>{children}</Shell>;
}

/** Full app chrome for players; a plain branded page for signed-out visitors (invite links). */
function MaybeShell({ children }: { children: React.ReactNode }) {
  const me = useMe();
  // No spinner here: unmounting the page while "me" loads would make the
  // page's own useMe retry the failed query on mount - an endless loop for
  // signed-out visitors. Plain layout until we know it's a player.
  if (me.data) return <Shell>{children}</Shell>;
  return (
    <div className="min-h-screen px-4 py-6">
      <Link to="/login" className="mx-auto mb-6 block w-fit">
        <Logo size={40} />
      </Link>
      {children}
    </div>
  );
}

export function App() {
  return (
    <>
    <NativeBridge />
    <Routes>
      <Route path="/login" element={<Login />} />
      {DEV_TOOLS && <Route path="/dev-login/:name" element={<DevLogin />} />}
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="/welcome" element={<Welcome />} />
      <Route path="/join/:code" element={<MaybeShell><JoinByCode /></MaybeShell>} />
      <Route path="/i/:code" element={<InviteLanding />} />
      <Route path="/" element={<Protected><Lobby /></Protected>} />
      <Route path="/tables" element={<Protected><MyTables /></Protected>} />
      <Route path="/tables/:id" element={<Protected><Suspense fallback={<Spinner />}><TableRoom /></Suspense></Protected>} />
      <Route path="/wallet" element={<Protected><WalletPage /></Protected>} />
      <Route path="/wallet/deposit/return" element={<Protected><DepositReturn /></Protected>} />
      <Route path="/friends" element={<Protected><Friends /></Protected>} />
      <Route path="/organize" element={<Protected><Organize /></Protected>} />
      <Route path="/profile" element={<Protected><Profile /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </>
  );
}
