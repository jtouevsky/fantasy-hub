#!/bin/bash
# Double-click this file to start Fantasy Hub. Close this window (or press Ctrl+C) to stop it.
cd "$(dirname "$0")"
source .venv/bin/activate
echo "Starting Fantasy Hub... your browser will open in a few seconds."
streamlit run app.py
