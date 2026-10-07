#!/bin/bash
# Double-click this file to start Fantasy Hub. Close this window (or press Ctrl+C) to stop it.
cd "$(dirname "$0")"
source .venv/bin/activate
if [ ! -d web/dist ]; then
  echo "Building the app (first run only)..."
  (cd web && npm install --silent && npm run build) || { echo "Build failed. Is Node.js installed? (https://nodejs.org)"; exit 1; }
fi
echo "Starting Fantasy Hub at http://localhost:8000 ..."
( sleep 3 && open "http://localhost:8000" ) &
uvicorn server.main:app --port 8000
