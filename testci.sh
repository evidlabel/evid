#!/bin/bash

# Set environment variables to simulate CI/headless mode
export HEADLESS=1
export QT_QPA_PLATFORM=offscreen
export CI=true

# Run pytest with uv
uv run pytest -v
