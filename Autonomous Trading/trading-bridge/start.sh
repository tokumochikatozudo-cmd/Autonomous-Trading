#!/bin/bash
set -e

echo "Starting Autonomous Trading Bot (LIVE MODE)..."
python -u main.py --live &

echo "Starting Autonomous Trading Bot (DEMO MODE)..."
python -u main.py --demo &

echo "Starting Web Dashboard..."
python -u run_dashboard.py
