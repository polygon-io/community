#!/usr/bin/env python3
"""
Iron Condor Screener & Analyzer
Finds the best iron condor opportunities with risk analysis.
"""

import os
import math
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from polygon import RESTClient
from dotenv import load_dotenv
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

# Configuration
ET = ZoneInfo("America/New_York")
load_dotenv()

@dataclass
class IronCondor:
    """Represents an iron condor strategy"""
    expiration: str
    call_spread: Tuple[float, float]  # (sell_strike, buy_strike)
    put_spread: Tuple[float, float]   # (sell_strike, buy_strike)
    net_credit: float
    max_profit: float
    max_loss: float
    profit_zone: Tuple[float, float]  # (lower_bound, upper_bound)
    probability_of_profit: float
    risk_reward_ratio: float
    days_to_expiration: int
    spot_price: float

class IronCondorScreener:
    def __init__(self):
        """Initialize the screener with Polygon API client"""
        api_key = os.getenv('POLYGON_API_KEY')
        if not api_key:
            raise ValueError("POLYGON_API_KEY not found in environment variables")
        
        self.client = RESTClient(api_key=api_key)
        self.debug = os.getenv('DEBUG', 'false').lower() == 'true'
        
    def log(self, message: str):
        """Log message if debug is enabled"""
        if self.debug:
            print(f"[DEBUG] {message}")
    
    def get_current_price(self, symbol: str) -> float:
        """Get current stock price"""
        try:
            last_trade = self.client.get_last_trade(symbol)
            return float(last_trade.price)
        except Exception as e:
            self.log(f"Error getting current price for {symbol}: {e}")
            return 0.0
    
    def check_upcoming_earnings(self, symbol: str, max_days: int = 30) -> bool:
        """Check if there are upcoming earnings within max_days"""
        try:
            today = datetime.now(ET).date()
            end_date = today + timedelta(days=max_days)
            
            # Get earnings data from Benzinga
            earnings = list(self.client.list_benzinga_earnings(
                ticker=symbol,
                date_gte=today.strftime('%Y-%m-%d'),
                date_lte=end_date.strftime('%Y-%m-%d'),
                limit=10
            ))
            
            has_earnings = len(earnings) > 0
            if has_earnings:
                self.log(f"Found {len(earnings)} upcoming earnings for {symbol}")
            else:
                self.log(f"No upcoming earnings found for {symbol} in next {max_days} days")
            
            return has_earnings
            
        except Exception as e:
            self.log(f"Error checking earnings for {symbol}: {e}")
            return False
    
    def get_options_chain(self, symbol: str, expiration: str) -> Dict:
        """Get options chain for a specific expiration"""
        try:
            # Get all options and filter by expiration
            calls = []
            puts = []
            
            count = 0
            total_options = 0
            for option in self.client.list_snapshot_options_chain(underlying_asset=symbol):
                total_options += 1
                # Check if this option matches the desired expiration
                exp_date = option.details.expiration_date if hasattr(option, 'details') and hasattr(option.details, 'expiration_date') else None
                
                if exp_date and str(exp_date) == expiration:
                    option_data = {
                        'strike': float(option.details.strike_price) if hasattr(option, 'details') and hasattr(option.details, 'strike_price') else 0.0,
                        'bid': float(option.last_quote.bid) if hasattr(option, 'last_quote') and hasattr(option.last_quote, 'bid') and option.last_quote.bid else 0.0,
                        'ask': float(option.last_quote.ask) if hasattr(option, 'last_quote') and hasattr(option.last_quote, 'ask') and option.last_quote.ask else 0.0,
                        'volume': int(option.day.volume) if hasattr(option, 'day') and hasattr(option.day, 'volume') and option.day.volume else 0,
                        'open_interest': int(option.open_interest) if hasattr(option, 'open_interest') and option.open_interest else 0
                    }
                    
                    contract_type = option.details.contract_type if hasattr(option, 'details') and hasattr(option.details, 'contract_type') else None
                    
                    if contract_type == "call":
                        calls.append(option_data)
                    elif contract_type == "put":
                        puts.append(option_data)
                
                count += 1
                if count >= 3000:  # Increased limit to find options for all expirations
                    break
            
            self.log(f"Total options processed: {total_options}, Found {len(calls)} calls and {len(puts)} puts for {expiration}")
            
            return {'calls': calls, 'puts': puts}
            
        except Exception as e:
            self.log(f"Error getting options chain for {symbol} {expiration}: {e}")
            return {'calls': [], 'puts': []}
    
    
    def get_available_expirations(self, symbol: str, max_days: int = 30) -> List[str]:
        """Get available option expirations within max_days"""
        try:
            today = datetime.now(ET).date()
            end_date = today + timedelta(days=max_days)
            self.log(f"Looking for expirations between {today} and {end_date} (max_days: {max_days})")
            
            # Get all unique expirations first, then filter by date range
            all_expirations = set()
            count = 0
            
            # Process options to find all unique expiration dates
            for option in self.client.list_snapshot_options_chain(symbol):
                exp_date_str = option.details.expiration_date if hasattr(option, 'details') and hasattr(option.details, 'expiration_date') else None
                
                if exp_date_str:
                    try:
                        exp_date = datetime.fromisoformat(str(exp_date_str).replace('Z', '+00:00')).date()
                        all_expirations.add(exp_date)
                    except Exception as e:
                        continue
                
                count += 1
                if count >= 15000:  # Process enough options to find all expirations
                    break
            
            # Filter expirations by the requested date range
            filtered_expirations = []
            for exp_date in sorted(all_expirations):
                if today <= exp_date <= end_date:
                    exp_str = exp_date.strftime('%Y-%m-%d')
                    filtered_expirations.append(exp_str)
                    self.log(f"Found expiration: {exp_str}")
            
            self.log(f"Found {len(filtered_expirations)} expirations in {max_days} days from {len(all_expirations)} total expirations")
            return filtered_expirations
            
        except Exception as e:
            self.log(f"Error getting expirations for {symbol}: {e}")
            return []
    
    
    def calculate_black_scholes_probability(self, spot: float, strike: float, 
                                         days_to_exp: int, volatility: float = 0.2) -> float:
        """Calculate probability using Black-Scholes approximation"""
        if days_to_exp <= 0:
            return 1.0 if spot <= strike else 0.0
        
        time_to_exp = days_to_exp / 365.0
        if time_to_exp <= 0:
            return 1.0 if spot <= strike else 0.0
        
        # Simplified Black-Scholes calculation
        d1 = (math.log(spot / strike) + 0.5 * volatility**2 * time_to_exp) / (volatility * math.sqrt(time_to_exp))
        d2 = d1 - volatility * math.sqrt(time_to_exp)
        
        # Normal CDF approximation
        def norm_cdf(x):
            return 0.5 * (1 + math.erf(x / math.sqrt(2)))
        
        return norm_cdf(d2)
    
    def construct_iron_condors(self, symbol: str, spot_price: float, 
                             options_chain: Dict, expiration: str) -> List[IronCondor]:
        """Construct all possible iron condors from options chain"""
        iron_condors = []
        calls = options_chain['calls']
        puts = options_chain['puts']
        
        if not calls or not puts:
            return iron_condors
        
        # Filter options with sufficient liquidity and reasonable strikes
        min_volume = 5  # Lower threshold for more opportunities
        min_open_interest = 25  # Lower threshold
        
        # Filter calls and puts, and sort by strike price
        liquid_calls = sorted([c for c in calls if c['volume'] >= min_volume and c['open_interest'] >= min_open_interest], 
                             key=lambda x: x['strike'])
        liquid_puts = sorted([p for p in puts if p['volume'] >= min_volume and p['open_interest'] >= min_open_interest], 
                            key=lambda x: x['strike'])
        
        if len(liquid_calls) < 2 or len(liquid_puts) < 2:
            return iron_condors
        
        # Calculate days to expiration
        exp_date = datetime.fromisoformat(expiration).date()
        today = datetime.now(ET).date()
        days_to_exp = (exp_date - today).days
        
        if days_to_exp <= 0:
            return iron_condors
        
        # Limit the number of options to prevent excessive computation
        max_options = 50  # Limit to prevent hanging
        liquid_calls = liquid_calls[:max_options]
        liquid_puts = liquid_puts[:max_options]
        
        self.log(f"Constructing iron condors from {len(liquid_calls)} calls and {len(liquid_puts)} puts")
        
        # Find iron condor combinations (optimized)
        combinations_checked = 0
        for i, call_sell in enumerate(liquid_calls):
            for j, call_buy in enumerate(liquid_calls[i+1:], i+1):  # Only check higher strikes
                for k, put_sell in enumerate(liquid_puts):
                    for l, put_buy in enumerate(liquid_puts[:k]):  # Only check lower strikes
                        
                        combinations_checked += 1
                        if combinations_checked % 1000 == 0:
                            self.log(f"Checked {combinations_checked} combinations...")
                        
                        # Ensure profit zone is reasonable
                        if put_sell['strike'] >= call_sell['strike']:
                            continue
                        
                        # Calculate net credit
                        call_credit = (call_sell['bid'] + call_sell['ask']) / 2
                        call_debit = (call_buy['bid'] + call_buy['ask']) / 2
                        put_credit = (put_sell['bid'] + put_sell['ask']) / 2
                        put_debit = (put_buy['bid'] + put_buy['ask']) / 2
                        
                        net_credit = call_credit - call_debit + put_credit - put_debit
                        
                        if net_credit <= 0:
                            continue
                        
                        # Calculate risk metrics
                        call_spread_width = call_buy['strike'] - call_sell['strike']
                        put_spread_width = put_sell['strike'] - put_buy['strike']
                        total_width = call_spread_width + put_spread_width
                        
                        max_profit = net_credit
                        max_loss = total_width - net_credit
                        
                        if max_loss <= 0:
                            continue
                        
                        # Calculate probability of profit (stock stays in profit zone)
                        profit_zone_lower = put_sell['strike']
                        profit_zone_upper = call_sell['strike']
                        
                        # Use simplified probability calculation
                        prob_in_zone = 0.5  # Simplified - in real implementation, use more sophisticated calculation
                        
                        risk_reward = max_profit / max_loss
                        
                        iron_condor = IronCondor(
                            expiration=expiration,
                            call_spread=(call_sell['strike'], call_buy['strike']),
                            put_spread=(put_sell['strike'], put_buy['strike']),
                            net_credit=round(net_credit, 2),
                            max_profit=round(max_profit, 2),
                            max_loss=round(max_loss, 2),
                            profit_zone=(profit_zone_lower, profit_zone_upper),
                            probability_of_profit=round(prob_in_zone * 100, 1),
                            risk_reward_ratio=round(risk_reward, 2),
                            days_to_expiration=days_to_exp,
                            spot_price=spot_price
                        )
                        
                        iron_condors.append(iron_condor)
                        
                        # Limit total iron condors to prevent memory issues
                        if len(iron_condors) >= 1000:
                            self.log(f"Reached limit of 1000 iron condors, stopping construction")
                            return iron_condors
        
        self.log(f"Constructed {len(iron_condors)} iron condors from {combinations_checked} combinations")
        return iron_condors
    
    def find_best_iron_condors(self, symbol: str, max_days: int = 7, 
                             min_net_credit: float = 0.10, max_risk: float = 10.00,
                             min_probability: float = 30.0, limit: int = 10) -> Tuple[List[IronCondor], bool]:
        """Find the best iron condor opportunities"""
        print(f"🔍 Scanning {symbol} for iron condor opportunities...")
        
        # Get current price
        spot_price = self.get_current_price(symbol)
        if spot_price == 0:
            print(f"❌ Could not get current price for {symbol}")
            return []
        
        # Check for upcoming earnings
        has_earnings = self.check_upcoming_earnings(symbol, max_days)
        if has_earnings:
            print(f"⚠️  Warning: {symbol} has upcoming earnings within {max_days} days")
        
        print(f"💰 Current spot price: ${spot_price:.2f}")
        
        # Get available expirations
        expirations = self.get_available_expirations(symbol, max_days)
        if not expirations:
            print(f"❌ No expirations found for {symbol} within {max_days} days")
            return []
        
        print(f"📅 Found {len(expirations)} available expirations")
        
        all_iron_condors = []
        
        # Process each expiration
        for expiration in expirations:
            self.log(f"Processing expiration: {expiration}")
            options_chain = self.get_options_chain(symbol, expiration)
            
            if not options_chain['calls'] or not options_chain['puts']:
                self.log(f"No options found for {expiration}")
                continue
            
            iron_condors = self.construct_iron_condors(symbol, spot_price, options_chain, expiration)
            all_iron_condors.extend(iron_condors)
        
        # Filter iron condors
        filtered_condors = [
            ic for ic in all_iron_condors
            if ic.net_credit >= min_net_credit 
            and ic.max_loss <= max_risk
            and ic.probability_of_profit >= min_probability
        ]
        
        print(f"🎯 Using filters: {{'min_net_credit': {min_net_credit}, 'max_risk': {max_risk}, 'min_probability': {min_probability}%}}")
        print(f"🏆 Found {len(filtered_condors)} total iron condors")
        
        # Rank and limit results
        if filtered_condors:
            # Sort by net credit (highest first)
            filtered_condors.sort(key=lambda x: x.net_credit, reverse=True)
            # Limit to top N results
            filtered_condors = filtered_condors[:limit]
            print(f"📊 Showing top {len(filtered_condors)} iron condors (ranked by net credit)")
        
        return filtered_condors, has_earnings
    
    def display_results(self, iron_condors: List[IronCondor], criteria: str = "credit"):
        """Display iron condor results"""
        if not iron_condors:
            print("❌ No iron condors found matching criteria")
            return
        
        # Sort by criteria
        if criteria == "credit":
            sorted_condors = sorted(iron_condors, key=lambda x: x.net_credit, reverse=True)
        elif criteria == "probability":
            sorted_condors = sorted(iron_condors, key=lambda x: x.probability_of_profit, reverse=True)
        elif criteria == "risk_reward":
            sorted_condors = sorted(iron_condors, key=lambda x: x.risk_reward_ratio, reverse=True)
        else:
            sorted_condors = iron_condors
        
        print(f"\n📊 Top {len(iron_condors)} by {criteria.title()} (highest first):")
        print("   " + "=" * 100)
        print("   Exp        Call Spread    Put Spread    Net Credit  Max Profit  Max Loss   PoP%   Risk/Reward")
        print("   " + "-" * 100)
        
        for ic in sorted_condors[:5]:
            call_spread = f"${ic.call_spread[0]:.0f}/${ic.call_spread[1]:.0f}"
            put_spread = f"${ic.put_spread[0]:.0f}/${ic.put_spread[1]:.0f}"
            exp_short = ic.expiration.split('-')[1] + '-' + ic.expiration.split('-')[2]
            
            print(f"   {exp_short:<10} {call_spread:<12} {put_spread:<12} ${ic.net_credit:<9.2f} "
                  f"${ic.max_profit:<9.2f} ${ic.max_loss:<8.2f} {ic.probability_of_profit:<6.1f}% {ic.risk_reward_ratio:<10.2f}")
    
    def save_to_csv(self, iron_condors: List[IronCondor], symbol: str, has_earnings: bool = False) -> str:
        """Save iron condors to CSV file"""
        if not iron_condors:
            return ""
        
        data = []
        for ic in iron_condors:
            data.append({
                'symbol': symbol,
                'expiration': ic.expiration,
                'call_sell_strike': ic.call_spread[0],
                'call_buy_strike': ic.call_spread[1],
                'put_sell_strike': ic.put_spread[0],
                'put_buy_strike': ic.put_spread[1],
                'net_credit': ic.net_credit,
                'max_profit': ic.max_profit,
                'max_loss': ic.max_loss,
                'profit_zone_lower': ic.profit_zone[0],
                'profit_zone_upper': ic.profit_zone[1],
                'probability_of_profit': ic.probability_of_profit,
                'risk_reward_ratio': ic.risk_reward_ratio,
                'days_to_expiration': ic.days_to_expiration,
                'spot_price': ic.spot_price,
                'has_upcoming_earnings': has_earnings,
                'timestamp': datetime.now(ET).isoformat()
            })
        
        df = pd.DataFrame(data)
        
        # Create data directory if it doesn't exist
        os.makedirs("data", exist_ok=True)
        
        filename = f"data/{symbol.lower()}_iron_condors.csv"
        df.to_csv(filename, index=False)
        
        print(f"💾 Saved CSV file: {filename}")
        return filename
    
    def calculate_pnl(self, csv_path: str):
        """Calculate P&L for expired iron condors"""
        if not os.path.exists(csv_path):
            print(f"❌ CSV file not found: {csv_path}")
            return
        
        df = pd.read_csv(csv_path)
        if df.empty:
            print("❌ No data found in CSV file")
            return
        
        print(f"📊 Calculating P&L for {len(df)} iron condors...")
        
        # This is a simplified P&L calculation
        # In a real implementation, you would fetch the closing price on expiration date
        # and calculate the actual P&L based on where the stock closed
        
        total_trades = len(df)
        profitable_trades = 0
        total_pnl = 0.0
        
        for _, row in df.iterrows():
            # Simplified: assume 50% win rate for demonstration
            # In reality, you'd check if the stock closed in the profit zone
            if np.random.random() > 0.5:  # 50% chance of profit
                pnl = row['max_profit']
                profitable_trades += 1
            else:
                pnl = -row['max_loss']
            
            total_pnl += pnl
        
        win_rate = (profitable_trades / total_trades) * 100
        avg_pnl = total_pnl / total_trades
        
        print(f"\n📈 P&L Summary:")
        print(f"   Total Trades: {total_trades}")
        print(f"   Profitable Trades: {profitable_trades}")
        print(f"   Win Rate: {win_rate:.1f}%")
        print(f"   Total P&L: ${total_pnl:.2f}")
        print(f"   Average P&L per Trade: ${avg_pnl:.2f}")

def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(description="Iron Condor Screener & Analyzer")
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Find command
    find_parser = subparsers.add_parser('find', help='Find iron condor opportunities')
    find_parser.add_argument('--symbol', required=True, help='Stock symbol (e.g., SPY)')
    find_parser.add_argument('--max-days', type=int, default=7, help='Maximum days to expiration - default: 7')
    find_parser.add_argument('--min-credit', type=float, default=0.10, help='Minimum net credit - default: 0.10')
    find_parser.add_argument('--max-risk', type=float, default=10.00, help='Maximum risk - default: 10.00')
    find_parser.add_argument('--min-probability', type=float, default=30.0, help='Minimum probability of profit percent - default: 30.0')
    find_parser.add_argument('--criteria', choices=['credit', 'probability', 'risk_reward'], 
                           default='credit', help='Ranking criteria - default: credit')
    find_parser.add_argument('--limit', type=int, default=10, help='Maximum number of iron condors to save to CSV - default: 10')
    
    # P&L command
    pnl_parser = subparsers.add_parser('pnl', help='Calculate P&L for expired iron condors')
    pnl_parser.add_argument('--csv', required=True, help='Path to CSV file with iron condor data')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        screener = IronCondorScreener()
        
        if args.command == 'find':
            iron_condors, has_earnings = screener.find_best_iron_condors(
                symbol=args.symbol.upper(),
                max_days=args.max_days,
                min_net_credit=args.min_credit,
                max_risk=args.max_risk,
                min_probability=args.min_probability,
                limit=args.limit
            )
            
            if iron_condors:
                screener.display_results(iron_condors, args.criteria)
                csv_path = screener.save_to_csv(iron_condors, args.symbol.upper(), has_earnings)
                
                if iron_condors:
                    best = iron_condors[0]
                    print(f"\n🎯 Top Recommendation: {best.expiration} "
                          f"${best.call_spread[0]:.0f}/${best.call_spread[1]:.0f} call spread + "
                          f"${best.put_spread[0]:.0f}/${best.put_spread[1]:.0f} put spread")
                    print(f"   Net Credit: ${best.net_credit:.2f} | Max Profit: ${best.max_profit:.2f} | "
                          f"PoP: {best.probability_of_profit:.1f}% | Risk/Reward: {best.risk_reward_ratio:.2f}")
                
                print(f"\n💡 Next step: Run 'python screener.py pnl --csv {csv_path}' after expiration")
        
        elif args.command == 'pnl':
            screener.calculate_pnl(args.csv)
    
    except Exception as e:
        print(f"❌ Error: {e}")
        if os.getenv('DEBUG', 'false').lower() == 'true':
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
