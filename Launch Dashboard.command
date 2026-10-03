#!/bin/bash
# Starts the app: the macOS twin of "Launch TGS.bat". Double-click in Finder.
cd "$(dirname "$0")/tgs-viz" || exit 1
echo "========================================"
echo "  Dashboard - Starting..."
echo "========================================"
echo
if ! command -v node >/dev/null 2>&1; then
  echo "  Node.js is not installed, or it is not on PATH."
  echo "  Install Node.js 22 LTS from nodejs.org, then start this again."
  read -rp "Press Enter to close. "
  exit 1
fi
if [ ! -e node_modules/.bin/vite ]; then
  echo "  The app's packages are not installed yet."
  echo "  Open a terminal in the tgs-viz folder and run:  npm install"
  echo "  Then start this again."
  read -rp "Press Enter to close. "
  exit 1
fi
npx vite --port 3000 --strictPort --open
rc=$?
if [ $rc -ne 0 ]; then
  echo
  echo "  The app stopped. If the message above says port 3000 is in use,"
  echo "  the app may already be running: use its browser tab, or close the"
  echo "  other Dashboard window first."
  read -rp "Press Enter to close. "
fi
exit $rc
