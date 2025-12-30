#!/bin/bash
set -e

echo "==============================================="
echo "Running database migrations..."
echo "==============================================="
python migrate_db.py

echo ""
echo "==============================================="
echo "Starting application..."
echo "==============================================="
exec uvicorn backend.main:app --host 0.0.0.0 --port $PORT
