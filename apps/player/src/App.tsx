import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Spinner } from "./components/bits";
import { Shell } from "./components/Shell";
import { useMe } from "./lib/hooks";
import { AuthCallback, Login, Welcome, rememberReturn } from "./pages/Auth";
import { Lobby } from "./pages/Lobby";
import { Profile } from "./pages/Profile";
import { Friends, JoinByCode, Organize } from "./pages/Social";
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
    return <Navigate to="/login" replace />;
  }
  if (!me.data.username || !me.data.terms_accepted) return <Navigate to="/welcome" replace />;
  return <Shell>{children}</Shell>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {import.meta.env.DEV && <Route path="/dev-login/:name" element={<DevLogin />} />}
      <Route path="/auth/callback" element={<AuthCallback />} />
      <Route path="/welcome" element={<Welcome />} />
      <Route path="/join/:code" element={<Shell><JoinByCode /></Shell>} />
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
