#!/bin/bash
set -e

echo "Starting Autonomous Trading Bot (LIVE MODE)..."
python -u main.py --live &


echo "Starting Web Dashboard..."
python -u run_dashboard.py
