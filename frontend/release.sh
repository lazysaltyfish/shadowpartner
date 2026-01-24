#!/usr/bin/env bash
set -euo pipefail

# Frontend release packer for ShadowPartner
# Packages static files for deployment

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
DIST_DIR="$PROJECT_ROOT/dist/frontend"
VERSION="${1:-$(git -C "$PROJECT_ROOT" describe --tags --always --dirty 2>/dev/null || echo 'dev')}"
TIMESTAMP="$(date +%s)"

echo "==> Packaging ShadowPartner frontend v$VERSION (timestamp: $TIMESTAMP)"

# Clean dist directory
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

# Copy static files
echo "  -> Copying HTML..."
cp "$FRONTEND_DIR/index.html" "$DIST_DIR/"

# Inject cache-busting timestamp into local JS/CSS references
echo "  -> Injecting cache-busting timestamps..."
sed -i \
    -e 's|href="css/\([^"]*\)"|href="css/\1?t='"$TIMESTAMP"'"|g' \
    -e 's|src="js/\([^"]*\)"|src="js/\1?t='"$TIMESTAMP"'"|g' \
    "$DIST_DIR/index.html"

echo "  -> Copying PWA files..."
cp "$FRONTEND_DIR/manifest.json" "$DIST_DIR/"
cp "$FRONTEND_DIR/service-worker.js" "$DIST_DIR/"

echo "  -> Copying CSS..."
mkdir -p "$DIST_DIR/css"
cp "$FRONTEND_DIR/css"/*.css "$DIST_DIR/css/" 2>/dev/null || true

echo "  -> Copying JS..."
mkdir -p "$DIST_DIR/js"
cp "$FRONTEND_DIR/js"/*.js "$DIST_DIR/js/"
mkdir -p "$DIST_DIR/js/composables"
cp "$FRONTEND_DIR/js/composables"/*.js "$DIST_DIR/js/composables/" 2>/dev/null || true

# Write version file
echo "$VERSION" > "$DIST_DIR/VERSION.txt"

# Create release tarball
TARBALL="$PROJECT_ROOT/dist/shadowpartner-frontend-$VERSION.tar.gz"
echo "  -> Creating tarball: $TARBALL"
tar -czf "$TARBALL" -C "$DIST_DIR" .

echo ""
echo "==> Done! Output: $TARBALL"
echo "    Contents:"
tar -tzf "$TARBALL" | sed 's/^/      /'
