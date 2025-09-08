import os, math, argparse
import pandas as pd
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from polygon import RESTClient
from dotenv import load_dotenv

ET = ZoneInfo("America/New_York")

# Load environment variables from .env file
load_dotenv()

def make_client():
    return RESTClient(api_key=os.getenv("POLYGON_API_KEY"))

def today_et() -> datetime:
    return datetime.now(ET)

def target_expiration_date(days_ahead: int) -> str:
    d = today_et().date() + timedelta(days=days_ahead)
    return d.strftime("%Y-%m-%d")

def minutes_to_close_on(date_str: str) -> float:
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    close_dt = datetime.combine(d, time(16, 0), tzinfo=ET)
    now = today_et()
    return max(0.0, (close_dt - now).total_seconds() / 60.0)

def time_to_expiry_years(date_str: str) -> float:
    mins = minutes_to_close_on(date_str)
    return max(mins / (60 * 24 * 365), 1e-6)

def fetch_chain_snapshot_calls(client, symbol: str, expiration_date: str):
    items = []
    for o in client.list_snapshot_options_chain(
        symbol,
        params={
            "contract_type": "call",
            "expiration_date.gte": expiration_date,
            "expiration_date.lte": expiration_date,
        },
    ):
        items.append(o)
    return items

def resolve_spot(chain, client, symbol: str) -> float | None:
    for o in chain:
        ua = getattr(o, "underlying_asset", None)
        if ua and getattr(ua, "price", None) is not None:
            return ua.price
    lt = client.get_last_trade(symbol)
    return getattr(lt, "price", None)

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))

def midpoint(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    return 0.5 * (bid + ask)

def pop_estimate(S0: float, breakeven: float, iv: float | None, t_years: float) -> float | None:
    if iv is None or iv <= 0 or breakeven <= 0 or t_years <= 0:
        return None
    d2 = (math.log(S0 / breakeven) - 0.5 * (iv ** 2) * t_years) / (iv * math.sqrt(t_years))
    return norm_cdf(d2)

def screen_candidates(chain,
                      spot: float,
                      expiration_date: str,
                      min_otm_pct=0.00,
                      max_otm_pct=0.03,
                      delta_lo=0.15,
                      delta_hi=0.35,
                      min_bid=0.05,
                      min_oi=1,
                      max_spread_to_mid=0.75,
                      rank_metric="premium_yield"):
    lo = spot * (1 + min_otm_pct)
    hi = spot * (1 + max_otm_pct) if max_otm_pct else float("inf")
    t_years = time_to_expiry_years(expiration_date)

    rows = []
    for o in chain:
        d = getattr(o, "details", None)
        q = getattr(o, "last_quote", None)
        g = getattr(o, "greeks", None)
        oi = getattr(o, "open_interest", 0) or 0
        iv = getattr(o, "implied_volatility", None)

        if not d or not q:
            continue

        k = d.strike_price
        if k is None or not (k >= lo and k <= hi):
            continue

        bid, ask = q.bid, q.ask
        if bid is None or ask is None or bid < min_bid:
            continue

        m = midpoint(bid, ask)
        if m is None or m <= 0:
            continue

        spread = ask - bid
        if m > 0 and (spread / m) > max_spread_to_mid:
            continue

        delta_ok = True
        delta_val = None
        if g and getattr(g, "delta", None) is not None:
            delta_val = abs(g.delta)
            delta_ok = (delta_lo <= delta_val <= delta_hi)
        if not delta_ok:
            continue

        breakeven = spot - m
        max_profit = (k - spot) + m
        pop = pop_estimate(spot, breakeven, iv, t_years)

        rows.append({
            "ticker": d.ticker,
            "expiration": d.expiration_date,
            "strike": k,
            "delta": delta_val,
            "bid": bid,
            "ask": ask,
            "mid": m,
            "open_interest": oi,
            "iv": iv,
            "spot": spot,
            "premium_yield": m / spot,
            "breakeven": breakeven,
            "max_profit": max_profit,
            "pop_est": pop,
        })

    if rank_metric == "premium_yield":
        rows.sort(key=lambda r: r["premium_yield"], reverse=True)
    elif rank_metric == "max_profit":
        rows.sort(key=lambda r: r["max_profit"], reverse=True)
    elif rank_metric == "pop_est":
        rows.sort(key=lambda r: (r["pop_est"] or 0), reverse=True)
    else:
        rows.sort(key=lambda r: r["premium_yield"], reverse=True)

    return rows

def save_csv(rows, outdir: str, symbol: str, expiration_date: str) -> str:
    Path(outdir).mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    path = Path(outdir) / f"{symbol.lower()}_{expiration_date}_0dte_calls.csv"
    df.to_csv(path, index=False)
    return str(path)

def mark_realized_pnl(csv_path: str, underlying_close: float) -> str:
    df = pd.read_csv(csv_path)
    S_close = float(underlying_close)
    per_share = []
    assigned = []
    for _, r in df.iterrows():
        K = float(r["strike"])
        S0 = float(r["spot"])
        c = float(r["mid"])
        if S_close <= K:
            p = (S_close - S0) + c
            assigned.append(False)
        else:
            p = (K - S0) + c
            assigned.append(True)
        per_share.append(p)
    df["assigned"] = assigned
    df["pnl_per_share"] = per_share
    df["pnl_per_contract"] = df["pnl_per_share"] * 100.0
    out = csv_path.replace(".csv", "_marked.csv")
    df.to_csv(out, index=False)
    return out

def main():
    ap = argparse.ArgumentParser(description="0-DTE covered-call screener")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sc = sub.add_parser("screen", help="Run the screener and write a CSV")
    sc.add_argument("--symbol", default="SPY")
    sc.add_argument("--expiration-days", type=int, default=0)
    sc.add_argument("--min-otm-pct", type=float, default=0.00)
    sc.add_argument("--max-otm-pct", type=float, default=0.03)
    sc.add_argument("--delta-lo", type=float, default=0.15)
    sc.add_argument("--delta-hi", type=float, default=0.35)
    sc.add_argument("--min-bid", type=float, default=0.05)
    sc.add_argument("--min-open-interest", type=int, default=1)
    sc.add_argument("--max-spread-to-mid", type=float, default=0.75)
    sc.add_argument("--rank-metric", choices=["premium_yield", "max_profit", "pop_est"], default="premium_yield")
    sc.add_argument("--outdir", default="./data")

    mk = sub.add_parser("mark", help="Compute realized P&L for a prior CSV")
    mk.add_argument("--csv", required=True)
    mk.add_argument("--underlying-close", required=True, type=float)

    args = ap.parse_args()

    if args.cmd == "screen":
        client = make_client()
        exp = target_expiration_date(args.expiration_days)
        chain = fetch_chain_snapshot_calls(client, args.symbol, exp)
        if not chain:
            raise SystemExit("No contracts returned (holiday/closed market or filters too strict).")
        spot = resolve_spot(chain, client, args.symbol)
        if spot is None:
            raise SystemExit("Could not resolve underlying spot.")
        rows = screen_candidates(
            chain,
            spot,
            exp,
            min_otm_pct=args.min_otm_pct,
            max_otm_pct=args.max_otm_pct,
            delta_lo=args.delta_lo,
            delta_hi=args.delta_hi,
            min_bid=args.min_bid,
            min_oi=args.min_open_interest,
            max_spread_to_mid=args.max_spread_to_mid,
            rank_metric=args.rank_metric,
        )
        if not rows:
            raise SystemExit("No candidates passed the filters.")
        path = save_csv(rows, args.outdir, args.symbol, exp)
        print(f"Wrote {len(rows)} rows to {path}")

    elif args.cmd == "mark":
        out = mark_realized_pnl(args.csv, args.underlying_close)
        print(f"Marked P&L written to {out}")

if __name__ == "__main__":
    main()