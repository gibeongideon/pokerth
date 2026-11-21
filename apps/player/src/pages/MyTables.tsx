import { Link } from "react-router-dom";
import { SeatDots, Spinner, StatusBadge } from "../components/bits";
import { useMyTables } from "../lib/hooks";

export function MyTables() {
  const tables = useMyTables(true, true);
  if (tables.isLoading) return <Spinner />;
  return (
    <div className="space-y-4">
      <h1 className="title text-3xl">My tables</h1>
      {!tables.data?.length ? (
        <div className="panel p-6 text-center">
          <div className="title text-xl">You're not at any table</div>
          <Link to="/" className="btn-gold mt-4">
            Find a game
          </Link>
        </div>
      ) : (
        tables.data.map((t) => (
          <Link key={t.id} to={`/tables/${t.id}`} className="panel flex items-center gap-4 p-4 hover:border-gold-400/40">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="font-display text-xl">{t.title ?? t.name}</span>
                <StatusBadge status={t.status} />
              </div>
              <div className="text-sm text-cream/60">{t.price_label}</div>
            </div>
            <SeatDots filled={t.players} total={t.seats_total} />
          </Link>
        ))
      )}
    </div>
  );
}
