import sqlite3
import pandas as pd

# Connect to the bot's memory
conn = sqlite3.connect("trading_bot.db")

print("--- POSITION DIAGNOSTICS ---")

# 1. Look at the exact status of the 5 positions
positions = pd.read_sql("""
    SELECT symbol, side, status, entry_price, exit_price, realized_pnl, holding_bars 
    FROM positions
""", conn)
print("\n1. All Positions:\n", positions)

# 2. Check your final equity (which includes UNREALIZED profit)
wallet = pd.read_sql("""
    SELECT usdt_balance, total_equity, open_positions 
    FROM wallet_snapshots 
    ORDER BY timestamp DESC LIMIT 1
""", conn)
print("\n2. Final Wallet State (includes floating PnL):\n", wallet)

conn.close()