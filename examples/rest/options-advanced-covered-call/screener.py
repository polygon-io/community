#!/usr/bin/env python3
"""
Advanced Covered Call Screener & Analyzer
Automatically finds the best covered call options with sophisticated profitability analysis.
Includes 7 advanced metrics for optimal trade selection and automatic P&L calculation.
"""

import os
import math
import argparse
import pandas as pd
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from polygon import RESTClient
from dotenv import load_dotenv

# Configuration
ET = ZoneInfo("America/New_York")
load_dotenv()


class OptionsScreener:
    """Main class for options screening and P&L calculation."""
    
    def __init__(self):
        self.client = RESTClient(api_key=os.getenv("POLYGON_API_KEY"))
    
    def _today_et(self) -> datetime:
        """Get current time in Eastern Time."""
        return datetime.now(ET)
    
    def _time_to_expiry_years(self, expiration_date: str) -> float:
        """Calculate time to expiry in years."""
        exp_dt = datetime.strptime(expiration_date, "%Y-%m-%d").date()
        close_dt = datetime.combine(exp_dt, time(16, 0), tzinfo=ET)
        now = self._today_et()
        minutes = max(0.0, (close_dt - now).total_seconds() / 60.0)
        return max(minutes / (60 * 24 * 365), 1e-6)
    
    def _fetch_options_chain(self, symbol: str, expiration_date: str):
        """Fetch options chain for a specific symbol and expiration."""
        items = []
        for option in self.client.list_snapshot_options_chain(
            symbol,
            params={
                "contract_type": "call",
                "expiration_date.gte": expiration_date,
                "expiration_date.lte": expiration_date,
            },
        ):
            items.append(option)
        return items
    
    def _resolve_spot_price(self, chain, symbol: str) -> float | None:
        """Get the current spot price of the underlying."""
        for option in chain:
            underlying = getattr(option, "underlying_asset", None)
            if underlying and getattr(underlying, "price", None) is not None:
                return underlying.price
        
        # Fallback to last trade
        last_trade = self.client.get_last_trade(symbol)
        return getattr(last_trade, "price", None)
    
    def _get_smart_filters(self, symbol: str, spot_price: float) -> dict:
        """Get appropriate filters based on symbol characteristics."""
        base_filters = {
            "min_otm_pct": 0.00,
            "max_otm_pct": 0.03,
            "delta_lo": 0.15,
            "delta_hi": 0.35,
            "min_bid": 0.05,
            "min_oi": 1,
            "max_spread_to_mid": 0.75,
        }
        
        # Adjust for different symbol types
        if symbol in ["SPY", "QQQ", "IWM", "SPX", "NDX"]:
            # ETFs - can be more restrictive
            base_filters.update({
                "max_otm_pct": 0.02,
                "delta_hi": 0.30,
                "min_oi": 100,
                "max_spread_to_mid": 0.50
            })
        elif symbol in ["NVDA", "TSLA", "AAPL", "MSFT", "AMZN", "GOOGL", "META"]:
            # High-volume tech stocks
            base_filters.update({
                "max_otm_pct": 0.05,
                "delta_lo": 0.10,
                "delta_hi": 0.40,
                "min_bid": 0.10,
                "min_oi": 50,
                "max_spread_to_mid": 1.0
            })
        elif spot_price > 200:
            # High-priced stocks
            base_filters.update({
                "max_otm_pct": 0.08,
                "delta_lo": 0.10,
                "delta_hi": 0.45,
                "min_bid": 0.20,
                "min_oi": 25,
                "max_spread_to_mid": 1.5
            })
        else:
            # General stocks
            base_filters.update({
                "max_otm_pct": 0.05,
                "delta_lo": 0.12,
                "delta_hi": 0.38,
                "min_bid": 0.10,
                "min_oi": 25,
                "max_spread_to_mid": 1.0
            })
        
        return base_filters
    
    def _screen_candidates(self, chain, spot: float, expiration_date: str, filters: dict):
        """Screen options based on criteria and return candidates."""
        t_years = self._time_to_expiry_years(expiration_date)
        lo = spot * (1 + filters["min_otm_pct"])
        hi = spot * (1 + filters["max_otm_pct"]) if filters["max_otm_pct"] else float("inf")
        
        candidates = []
        
        for option in chain:
            details = getattr(option, "details", None)
            quote = getattr(option, "last_quote", None)
            greeks = getattr(option, "greeks", None)
            open_interest = getattr(option, "open_interest", 0) or 0
            iv = getattr(option, "implied_volatility", None)
            
            if not details or not quote:
                continue
            
            strike = details.strike_price
            if strike is None or not (lo <= strike <= hi):
                continue
            
            bid, ask = quote.bid, quote.ask
            if bid is None or ask is None or bid < filters["min_bid"]:
                continue
            
            # Calculate midpoint
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            mid = 0.5 * (bid + ask)
            
            # Check spread
            spread = ask - bid
            if mid > 0 and (spread / mid) > filters["max_spread_to_mid"]:
                continue
            
            # Check delta
            delta_ok = True
            delta_val = None
            if greeks and getattr(greeks, "delta", None) is not None:
                delta_val = abs(greeks.delta)
                delta_ok = filters["delta_lo"] <= delta_val <= filters["delta_hi"]
            
            if not delta_ok or open_interest < filters["min_oi"]:
                continue
            
            # Calculate basic metrics
            breakeven = spot - mid
            max_profit = (strike - spot) + mid
            pop = self._calculate_pop(spot, breakeven, iv, t_years)
            
            # Calculate advanced profitability metrics
            advanced_metrics = self._calculate_advanced_metrics(
                spot, strike, mid, pop, max_profit, iv, t_years, 
                bid, ask, open_interest, expiration_date
            )
            
            candidates.append({
                "ticker": details.ticker,
                "expiration": details.expiration_date,
                "strike": strike,
                "delta": delta_val,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "open_interest": open_interest,
                "iv": iv,
                "spot": spot,
                "premium_yield": mid / spot,
                "breakeven": breakeven,
                "max_profit": max_profit,
                "pop_est": pop,
                **advanced_metrics  # Add all advanced metrics
            })
        
        # Sort by premium yield
        candidates.sort(key=lambda x: x["premium_yield"], reverse=True)
        return candidates
    
    def _calculate_pop(self, spot: float, breakeven: float, iv: float | None, t_years: float) -> float | None:
        """Calculate probability of profit using Black-Scholes approximation."""
        if iv is None or iv <= 0 or breakeven <= 0 or t_years <= 0:
            return None
        
        d2 = (math.log(spot / breakeven) - 0.5 * (iv ** 2) * t_years) / (iv * math.sqrt(t_years))
        return 0.5 * (1.0 + math.erf(d2 / math.sqrt(2)))
    
    def _calculate_advanced_metrics(self, spot: float, strike: float, premium: float, 
                                  pop: float | None, max_profit: float, iv: float | None, 
                                  t_years: float, bid: float, ask: float, 
                                  open_interest: int, expiration_date: str) -> dict:
        """Calculate advanced profitability metrics."""
        metrics = {}
        
        # 1. Expected Value (EV) - Most critical for profitability
        if pop is not None:
            # For covered calls: 
            # Win scenario (not assigned): Keep premium
            # Loss scenario (assigned): Premium + (strike - spot) - opportunity cost
            # Simplified: Expected value = premium (since we always keep premium)
            # But we can factor in the probability of assignment vs keeping premium
            win_amount = premium  # Always keep premium
            loss_amount = premium  # Even if assigned, we keep premium (stock called away at strike)
            expected_value = (pop * win_amount) + ((1 - pop) * loss_amount)
            metrics["expected_value"] = expected_value
            metrics["expected_value_pct"] = expected_value / spot
        else:
            metrics["expected_value"] = None
            metrics["expected_value_pct"] = None
        
        # 2. Time Decay (Theta) Analysis
        days_to_expiry = self._days_to_expiry(expiration_date)
        if days_to_expiry > 0:
            daily_theta = premium / days_to_expiry
            metrics["daily_theta"] = daily_theta
            metrics["theta_efficiency"] = daily_theta / spot  # Theta per dollar invested
        else:
            metrics["daily_theta"] = None
            metrics["theta_efficiency"] = None
        
        # 3. Liquidity Score
        spread = ask - bid
        if bid > 0 and spread > 0:
            # Higher is better: more volume/OI, lower spread
            liquidity_score = (open_interest * 1000) / (spread / bid)  # Scale OI for better numbers
            metrics["liquidity_score"] = liquidity_score
        else:
            metrics["liquidity_score"] = 0
        
        # 4. Volatility-Adjusted Premium
        if iv is not None and iv > 0 and t_years > 0:
            vol_adjusted_premium = premium / (iv * math.sqrt(t_years))
            metrics["vol_adjusted_premium"] = vol_adjusted_premium
        else:
            metrics["vol_adjusted_premium"] = None
        
        # 5. Capital Efficiency
        capital_at_risk = max(0, strike - spot)  # Capital tied up if assigned
        if capital_at_risk > 0:
            capital_efficiency = premium / capital_at_risk
            metrics["capital_efficiency"] = capital_efficiency
        else:
            metrics["capital_efficiency"] = float('inf') if premium > 0 else 0
        
        # 6. Risk-Adjusted Return (Sharpe-like)
        if pop is not None and expected_value is not None:
            # Use IV as proxy for risk
            risk_proxy = iv if iv is not None else 0.2  # Default 20% if no IV
            if risk_proxy > 0:
                risk_adjusted_return = expected_value / (risk_proxy * spot)
                metrics["risk_adjusted_return"] = risk_adjusted_return
            else:
                metrics["risk_adjusted_return"] = None
        else:
            metrics["risk_adjusted_return"] = None
        
        # 7. Premium-to-Risk Ratio
        max_loss = max(0, (strike - spot) - premium)  # Define max_loss here
        if max_loss > 0:
            premium_to_risk = premium / max_loss
            metrics["premium_to_risk"] = premium_to_risk
        else:
            metrics["premium_to_risk"] = float('inf') if premium > 0 else 0
        
        return metrics
    
    def _days_to_expiry(self, expiration_date: str) -> int:
        """Calculate days to expiration."""
        try:
            from datetime import datetime, date
            exp_date = datetime.strptime(expiration_date, "%Y-%m-%d").date()
            today = date.today()
            return (exp_date - today).days
        except:
            return 0
    
    def _find_available_expirations(self, symbol: str, max_days_ahead: int = 30):
        """Find all available expiration dates for a symbol."""
        expirations = set()
        start_date = self._today_et().date()
        
        for days_ahead in range(max_days_ahead + 1):
            exp_date = start_date + timedelta(days=days_ahead)
            exp_date_str = exp_date.strftime("%Y-%m-%d")
            
            try:
                chain = self._fetch_options_chain(symbol, exp_date_str)
                if chain:
                    expirations.add(exp_date_str)
            except Exception:
                continue
        
        return sorted(list(expirations))
    
    def find_best_options(self, symbol: str, max_days_ahead: int = 7, max_options: int = 5):
        """Find the best covered call options across all available expirations."""
        print(f"🔍 Scanning {symbol} for available expirations...")
        
        # Find available expirations
        expirations = self._find_available_expirations(symbol, max_days_ahead)
        if not expirations:
            print(f"❌ No options found for {symbol} in the next {max_days_ahead} days")
            return None
        
        print(f"📅 Found {len(expirations)} available expirations: {expirations}")
        
        # Get spot price and filters
        sample_chain = self._fetch_options_chain(symbol, expirations[0])
        spot = self._resolve_spot_price(sample_chain, symbol)
        if spot is None:
            print(f"❌ Could not resolve spot price for {symbol}")
            return None
        
        print(f"💰 Current spot price: ${spot:.2f}")
        filters = self._get_smart_filters(symbol, spot)
        print(f"🎯 Using filters: {filters}")
        
        # Collect all candidates across all expirations
        all_candidates = []
        
        for exp_date in expirations:
            print(f"📊 Checking expiration: {exp_date}")
            
            try:
                chain = self._fetch_options_chain(symbol, exp_date)
                if not chain:
                    continue
                
                candidates = self._screen_candidates(chain, spot, exp_date, filters)
                
                if candidates:
                    # Add expiration date to each candidate
                    for candidate in candidates:
                        candidate["expiration"] = exp_date
                        # Calculate different scoring metrics
                        candidate["score_premium"] = candidate["premium_yield"]
                        candidate["score_pop"] = candidate["pop_est"] or 0.5
                        candidate["score_balanced"] = candidate["premium_yield"] * (candidate["pop_est"] or 0.5)
                        candidate["score_max_profit"] = candidate["max_profit"] / spot
                        
                        # Advanced scoring metrics (normalize to 0-1 range)
                        ev_pct = candidate.get("expected_value_pct", 0) or 0
                        candidate["score_expected_value"] = max(0, min(1, ev_pct * 100))  # Scale EV% to 0-1
                        
                        risk_adj = candidate.get("risk_adjusted_return", 0) or 0
                        candidate["score_risk_adjusted"] = max(0, min(1, risk_adj * 10))  # Scale risk-adjusted
                        
                        theta_eff = candidate.get("theta_efficiency", 0) or 0
                        candidate["score_theta_efficiency"] = max(0, min(1, theta_eff * 1000))  # Scale theta
                        
                        liquidity = candidate.get("liquidity_score", 0) or 0
                        candidate["score_liquidity"] = max(0, min(1, liquidity / 1000000))  # Scale liquidity
                        
                        cap_eff = candidate.get("capital_efficiency", 0) or 0
                        candidate["score_capital_efficiency"] = max(0, min(1, cap_eff / 10))  # Cap at 1
                        
                        # Composite scores
                        candidate["score_profitable"] = (
                            candidate["score_expected_value"] * 0.4 +  # 40% weight on EV
                            candidate["score_risk_adjusted"] * 0.3 +   # 30% weight on risk-adjusted
                            candidate["score_theta_efficiency"] * 0.2 + # 20% weight on time decay
                            candidate["score_liquidity"] * 0.1        # 10% weight on liquidity
                        )
                        
                        candidate["score_aggressive"] = (
                            candidate["score_premium"] * 0.5 +         # 50% weight on premium
                            candidate["score_expected_value"] * 0.3 +  # 30% weight on EV
                            candidate["score_capital_efficiency"] * 0.2 # 20% weight on capital efficiency
                        )
                    
                    all_candidates.extend(candidates)
                    print(f"  ✅ Found {len(candidates)} candidates")
                else:
                    print(f"  ❌ No candidates found")
                    
            except Exception as e:
                print(f"  ⚠️ Error checking {exp_date}: {e}")
                continue
        
        if not all_candidates:
            print(f"❌ No suitable options found for {symbol}")
            return None
        
        # Sort by different criteria and get top options
        top_options = {
            "premium": sorted(all_candidates, key=lambda x: x["score_premium"], reverse=True)[:max_options],
            "probability": sorted(all_candidates, key=lambda x: x["score_pop"], reverse=True)[:max_options],
            "balanced": sorted(all_candidates, key=lambda x: x["score_balanced"], reverse=True)[:max_options],
            "max_profit": sorted(all_candidates, key=lambda x: x["score_max_profit"], reverse=True)[:max_options],
            "expected_value": sorted(all_candidates, key=lambda x: x["score_expected_value"], reverse=True)[:max_options],
            "profitable": sorted(all_candidates, key=lambda x: x["score_profitable"], reverse=True)[:max_options],
            "aggressive": sorted(all_candidates, key=lambda x: x["score_aggressive"], reverse=True)[:max_options]
        }
        
        # Display results
        print(f"\n🏆 Found {len(all_candidates)} total candidates. Top options by different criteria:")
        
        for criteria, options in top_options.items():
            if not options:
                continue
                
            print(f"\n📊 Top {len(options)} by {criteria.replace('_', ' ').title()}:")
            
            # Choose display format based on criteria
            if criteria in ["expected_value", "profitable", "aggressive"]:
                # Advanced metrics display
                print("   " + "="*140)
                print(f"   {'Exp':<8} {'Strike':<7} {'Premium':<7} {'EV%':<6} {'RiskAdj':<7} {'Theta':<6} {'Liq':<6} {'Score':<7}")
                print("   " + "-"*140)
                
                for i, option in enumerate(options, 1):
                    exp_short = option["expiration"][-5:]  # Just MM-DD
                    ev_pct = (option.get("expected_value_pct", 0) or 0) * 100
                    risk_adj = option.get("risk_adjusted_return", 0) or 0
                    theta_eff = (option.get("theta_efficiency", 0) or 0) * 1000  # Scale for display
                    liquidity = (option.get("liquidity_score", 0) or 0) / 1000000  # Scale for display
                    
                    # Map criteria to score keys
                    score_key_map = {
                        "premium": "score_premium",
                        "probability": "score_pop", 
                        "balanced": "score_balanced",
                        "max_profit": "score_max_profit",
                        "expected_value": "score_expected_value",
                        "profitable": "score_profitable",
                        "aggressive": "score_aggressive"
                    }
                    score = option[score_key_map[criteria]]
                    
                    print(f"   {exp_short:<8} ${option['strike']:<6} ${option['mid']:<6.3f} {ev_pct:<5.2f}% {risk_adj:<6.3f} {theta_eff:<5.1f} {liquidity:<5.0f} {score:<6.4f}")
            else:
                # Standard metrics display
                print("   " + "="*120)
                print(f"   {'Exp':<10} {'Strike':<8} {'Premium':<8} {'Yield%':<7} {'Delta':<6} {'PoP%':<6} {'Max$':<8} {'Score':<8}")
                print("   " + "-"*120)
                
                for i, option in enumerate(options, 1):
                    exp_short = option["expiration"][-5:]  # Just MM-DD
                    yield_pct = option["premium_yield"] * 100
                    pop_pct = (option["pop_est"] or 0) * 100
                    max_profit = option["max_profit"]
                    # Map criteria to score keys
                    score_key_map = {
                        "premium": "score_premium",
                        "probability": "score_pop", 
                        "balanced": "score_balanced",
                        "max_profit": "score_max_profit",
                        "expected_value": "score_expected_value",
                        "profitable": "score_profitable",
                        "aggressive": "score_aggressive"
                    }
                    score = option[score_key_map[criteria]]
                    
                    print(f"   {exp_short:<10} ${option['strike']:<7} ${option['mid']:<7.3f} {yield_pct:<6.2f}% {option['delta']:<5.3f} {pop_pct:<5.1f}% ${max_profit:<7.2f} {score:<7.4f}")
        
        # Return the balanced score winner as the "best" option
        best_option = top_options["balanced"][0] if top_options["balanced"] else all_candidates[0]
        
        return {
            "best_option": best_option,
            "all_options": all_candidates,
            "top_by_criteria": top_options,
            "spot": spot
        }
    
    def calculate_pnl(self, csv_path: str):
        """Calculate P&L for trades by automatically fetching closing prices."""
        df = pd.read_csv(csv_path)
        results = []
        
        print(f"🔄 Calculating P&L for {len(df)} trades...")
        
        for _, row in df.iterrows():
            expiration = row["expiration"]
            strike = float(row["strike"])
            spot_at_trade = float(row["spot"])
            premium = float(row["mid"])
            
            try:
                # Extract symbol from ticker (e.g., "O:SPY250923C00665000" -> "SPY")
                ticker = row["ticker"]
                symbol = ticker.split(":")[1].split("C")[0]
                
                # Fetch closing price
                close_data = self.client.get_daily_open_close_agg(symbol, expiration)
                close_price = close_data.close
                
                # Calculate P&L
                if close_price <= strike:
                    pnl_per_share = premium
                    assigned = False
                else:
                    pnl_per_share = premium + (strike - spot_at_trade)
                    assigned = True
                
                pnl_per_contract = pnl_per_share * 100
                
                results.append({
                    "expiration": expiration,
                    "strike": strike,
                    "premium": premium,
                    "spot_at_trade": spot_at_trade,
                    "close_price": close_price,
                    "assigned": assigned,
                    "pnl_per_share": pnl_per_share,
                    "pnl_per_contract": pnl_per_contract,
                    "delta": row.get("delta"),
                    "premium_yield": row.get("premium_yield")
                })
                
                print(f"  ✅ {expiration}: Strike ${strike}, Close ${close_price:.2f}, P&L: ${pnl_per_contract:.2f}")
                
            except Exception as e:
                print(f"  ⚠️ Could not get closing price for {expiration}: {e}")
                results.append({
                    "expiration": expiration,
                    "strike": strike,
                    "premium": premium,
                    "spot_at_trade": spot_at_trade,
                    "close_price": None,
                    "assigned": None,
                    "pnl_per_share": None,
                    "pnl_per_contract": None,
                    "delta": row.get("delta"),
                    "premium_yield": row.get("premium_yield")
                })
        
        # Calculate summary
        valid_trades = [r for r in results if r["pnl_per_contract"] is not None]
        if valid_trades:
            total_pnl = sum(r["pnl_per_contract"] for r in valid_trades)
            win_rate = sum(1 for r in valid_trades if r["pnl_per_contract"] > 0) / len(valid_trades) * 100
            
            print(f"\n📊 P&L Summary:")
            print(f"   Valid Trades: {len(valid_trades)}")
            print(f"   Total P&L: ${total_pnl:.2f}")
            print(f"   Win Rate: {win_rate:.1f}%")
            print(f"   Avg P&L per Trade: ${total_pnl/len(valid_trades):.2f}")
        
        # Save results
        results_df = pd.DataFrame(results)
        output_path = csv_path.replace(".csv", "_pnl.csv")
        results_df.to_csv(output_path, index=False)
        print(f"\n💾 P&L results saved to: {output_path}")
        
        return output_path


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description="Advanced Covered Call Screener & Analyzer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Find best option command
    find_parser = subparsers.add_parser("find", help="Find the best covered call options")
    find_parser.add_argument("--symbol", default="SPY", help="Symbol to screen")
    find_parser.add_argument("--max-days", type=int, default=7, help="Maximum days ahead to search")
    find_parser.add_argument("--max-options", type=int, default=5, help="Maximum number of options to show per criteria")
    find_parser.add_argument("--criteria", default="profitable", 
                           choices=["premium", "probability", "balanced", "max_profit", "expected_value", "profitable", "aggressive"],
                           help="Ranking criteria for CSV output (default: profitable)")
    find_parser.add_argument("--outdir", default="./data", help="Output directory")
    
    # Calculate P&L command
    pnl_parser = subparsers.add_parser("pnl", help="Calculate P&L for trades")
    pnl_parser.add_argument("--csv", required=True, help="CSV file with trade data")
    pnl_parser.add_argument("--outdir", default="./data", help="Output directory")
    
    args = parser.parse_args()
    
    screener = OptionsScreener()
    
    if args.command == "find":
        result = screener.find_best_options(args.symbol, args.max_days, args.max_options)
        
        if result:
            # Save one CSV file based on selected criteria
            Path(args.outdir).mkdir(parents=True, exist_ok=True)
            
            # Get options for the selected criteria
            selected_options = result["top_by_criteria"].get(args.criteria, [])
            if not selected_options:
                print(f"❌ No options found for criteria: {args.criteria}")
                return
            
            # Add spot price to each option
            for option in selected_options:
                option["spot"] = result["spot"]
            
            # Save the selected options
            df = pd.DataFrame(selected_options)
            filename = f"{args.symbol.lower()}_{args.criteria}_options.csv"
            output_path = Path(args.outdir) / filename
            df.to_csv(output_path, index=False)
            
            # Get the top option from the selected criteria
            top_option = selected_options[0]
            
            print(f"\n💾 Saved CSV file: {output_path}")
            print(f"   📊 Criteria: {args.criteria.replace('_', ' ').title()}")
            print(f"   📈 Options: {len(selected_options)} options")
            
            print(f"\n🎯 Top Recommendation: Sell the {top_option['expiration']} ${top_option['strike']} call for ${top_option['mid']:.3f}")
            print(f"   Premium Yield: {top_option['premium_yield']*100:.2f}% | PoP: {top_option['pop_est']*100:.1f}% | Delta: {top_option['delta']:.3f}")
            print(f"\n💡 Next step: Run 'python screener.py pnl --csv {output_path}' after expiration")
            print(f"\n📋 Other ranking criteria available:")
            print(f"   • Premium: Highest income potential")
            print(f"   • Probability: Safest options (least likely to be assigned)")
            print(f"   • Balanced: Best risk/reward combination")
            print(f"   • Max Profit: Highest total profit potential")
            print(f"   • Expected Value: Best mathematical edge (most profitable long-term)")
            print(f"   • Profitable: Advanced risk-adjusted scoring (current selection)")
            print(f"   • Aggressive: High premium + capital efficiency")
            print(f"\n💡 To use a different criteria, run: python screener.py find --criteria [criteria_name]")
        else:
            print(f"\n❌ No suitable options found for {args.symbol}")
            print("💡 Try different symbol or increase --max-days")
    
    elif args.command == "pnl":
        screener.calculate_pnl(args.csv)


if __name__ == "__main__":
    main()
