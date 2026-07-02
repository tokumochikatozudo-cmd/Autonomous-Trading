"""
run_dashboard.py
────────────────
Standalone launcher for the Trading Bridge AI web dashboard.
Run this independently from main.py so the dashboard always stays accessible,
even while the main trading loop is sleeping between 1-hour cycles.

Usage:
    python run_dashboard.py
"""
import uvicorn
import sys
import os

# Add the project root to path so imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monitoring.server import app

if __name__ == "__main__":
    print("🚀 Starting Dashboard Server...")
    print("  Open your browser at: http://localhost:8080")
    print("  (Press CTRL+C to stop)")
    
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
