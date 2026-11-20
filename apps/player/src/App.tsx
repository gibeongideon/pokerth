import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Spinner } from "./components/bits";
import { Logo } from "./components/Brand";
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

// The table (PixiJS + game protocol) is the heaviest screen: load it on demand.
const TableRoom = lazy(() => import("./pages/TableRoom").then((m) => ({ default: m.TableRoom })));

function Protected({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isLoading) return <Spinner />;
  if (!me.data) {
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
    <Routes>
      <Route path="/login" element={<Login />} />
      {import.meta.env.DEV && <Route path="/dev-login/:name" element={<DevLogin />} />}
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
  );
}
