#!/bin/bash
set -e

echo "Starting Autonomous Trading Bot (LIVE MODE)..."
python main.py --live &

echo "Starting Autonomous Trading Bot (DEMO MODE)..."
python main.py --demo &

echo "Starting Web Dashboard..."
python run_dashboard.py
