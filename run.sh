#!/bin/bash
# Claude Usage Monitor launcher
cd "$(dirname "$0")"
exec python3 monitor.py "$@"
