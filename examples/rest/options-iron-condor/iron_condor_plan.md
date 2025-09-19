# Iron Condor Screener - Build Plan

## Project Overview
Create a standalone iron condor screener inspired by the existing covered call screener architecture. This will be a separate repository with a single-file implementation.

## Project Structure (Minimal)
```
iron_condor_screener/
├── README.md                    # Basic documentation  
├── pyproject.toml               # Dependencies
├── env.example                  # Environment template
├── LICENSE                      # MIT license
├── screener.py                  # ALL CODE HERE (single file)
└── data/                        # CSV outputs
    └── .gitkeep
```

## Single File Implementation (`screener.py`)
All code in one file, following the current covered call screener pattern:

```python
#!/usr/bin/env python3
"""
Iron Condor Screener & Analyzer
Finds the best iron condor opportunities with risk analysis.
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

class IronCondorScreener:
    def __init__(self):
        # Polygon API setup
        
    def find_best_iron_condors(self, symbol, max_days=7):
        # 1. Fetch calls and puts for all expirations
        # 2. Construct iron condor combinations  
        # 3. Calculate risk metrics (max profit, max loss, PoP)
        # 4. Rank by different criteria
        # 5. Display results and save CSV
        
    def calculate_pnl(self, csv_path):
        # Calculate P&L for expired iron condors

def main():
    # CLI interface with find/pnl commands
```

## Core Features

### 1. Iron Condor Construction
- Find call spreads (sell lower call, buy higher call)  
- Find put spreads (sell higher put, buy lower put)
- Combine into iron condor (4 legs total)
- Calculate net credit received

### 2. Risk Metrics
- **Max Profit**: Net credit collected
- **Max Loss**: Spread width - net credit  
- **Profit Zone**: Range between sold strikes
- **Probability of Profit**: Using Black-Scholes
- **Risk/Reward Ratio**: Max profit / max loss

### 3. CLI Commands
```bash
# Find iron condors
python screener.py find --symbol SPY

# Different criteria
python screener.py find --symbol SPY --criteria probability

# Calculate P&L  
python screener.py pnl --csv data/spy_iron_condors.csv
```

### 4. Ranking Criteria
- **Credit**: Highest premium collected
- **Probability**: Highest chance of profit
- **Risk/Reward**: Best profit vs loss ratio
- **Balanced**: Combination of above

## Key Implementation Details

### Iron Condor Structure
An Iron Condor consists of 4 legs:
- **Sell Call Spread**: Sell lower call, Buy higher call
- **Sell Put Spread**: Sell higher put, Buy lower put
- **Same Expiration**: All 4 legs must have same expiration
- **Net Credit**: Collect premium from both spreads

### Risk Calculations
- **Max Profit**: Net credit received (if stock stays between sold strikes)
- **Max Loss**: (Call spread width + Put spread width) - Net credit
- **Profit Zone**: Between the two sold strikes
- **Breakevens**: Sold call strike - net credit, Sold put strike + net credit

### Screening Logic
1. Fetch options chains for calls and puts
2. Find available expirations (similar to current screener)
3. For each expiration, construct iron condor combinations
4. Filter by:
   - Minimum net credit
   - Maximum risk
   - Minimum profit zone width
   - Days to expiration
   - Liquidity requirements
5. Calculate metrics and rank by different criteria
6. Display results and save to CSV

### P&L Calculation
- Fetch closing price on expiration date
- Determine if stock closed in profit zone
- Calculate actual P&L based on final stock price
- Generate P&L summary with win rate

## Dependencies
```toml
# pyproject.toml
[project]
name = "iron-condor-screener"
version = "0.1.0"
description = "Iron Condor Screener & Analyzer"
dependencies = [
    "polygon-api-client>=1.0.0",
    "pandas>=2.0.0",
    "python-dotenv>=1.0.0"
]
```

## Environment Setup
```bash
# .env file
POLYGON_API_KEY=your_api_key_here
```

## Key Simplifications
1. **Single file** - Everything in `screener.py`
2. **No tests** - Keep it simple like current repo
3. **Minimal dependencies** - Only essential packages
4. **Simple CLI** - Just `find` and `pnl` commands
5. **Basic filtering** - Essential filters only
6. **Clear output** - Similar to current screener format

## Expected Output Format
```
🔍 Scanning SPY for iron condor opportunities...
📅 Found 6 available expirations
💰 Current spot price: $660.30
🎯 Using filters: {'min_net_credit': 0.50, 'max_risk': 2.00, ...}

🏆 Found 12 total iron condors. Top options by different criteria:

📊 Top 5 by Credit:
   =====================================================================================================
   Exp        Call Spread    Put Spread    Net Credit  Max Profit  Max Loss   PoP%   Risk/Reward
   -----------------------------------------------------------------------------------------------------
   09-23      $665/$670      $650/$645     $1.25       $1.25       $3.75      68.2%  0.33
   09-19      $666/$671      $651/$646     $1.15       $1.15       $3.85      67.8%  0.30

📊 Top 5 by Probability:
   =====================================================================================================
   Exp        Call Spread    Put Spread    Net Credit  Max Profit  Max Loss   PoP%   Risk/Reward
   -----------------------------------------------------------------------------------------------------
   09-16      $661/$666      $656/$651     $0.85       $0.85       $4.15      72.1%  0.20

💾 Saved CSV file: data/spy_iron_condors.csv
🎯 Top Recommendation: 2025-09-23 $665/$670 call spread + $650/$645 put spread
   Net Credit: $1.25 | Max Profit: $1.25 | PoP: 68.2% | Risk/Reward: 0.33

💡 Next step: Run 'python screener.py pnl --csv data/spy_iron_condors.csv' after expiration
```

## Implementation Notes
- Use the existing covered call screener as a reference for API integration, CLI structure, and output formatting
- Focus on the 4-leg complexity of iron condors vs single-leg covered calls
- Ensure all 4 legs are available and liquid before constructing an iron condor
- Calculate probability of profit using the profit zone (between sold strikes)
- Handle edge cases like missing legs or insufficient liquidity gracefully

This plan maintains the same high-quality approach as the current covered call screener while adding the sophistication needed for iron condor strategies.
