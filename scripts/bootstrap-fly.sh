#!/usr/bin/env bash
set -euo pipefail

# One-time Fly.io bootstrap for fire-mint.
# Usage: APP_NAME=fire-mint ./scripts/bootstrap-fly.sh

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="${APP_NAME:-}"

if [[ -z "$APP_NAME" ]]; then
  echo "Set APP_NAME (lowercase, unique on Fly), e.g.:"
  echo "  APP_NAME=fire-mint ./scripts/bootstrap-fly.sh"
  exit 1
fi

if ! command -v fly &>/dev/null; then
  echo "Install flyctl: https://fly.io/docs/flyctl/install/"
  exit 1
fi

echo "==> Patching fly/fly.toml (app = ${APP_NAME})"
sed -E -i.bak "s|^app = \".*\"|app = \"${APP_NAME}\"|" "$ROOT/fly/fly.toml"
rm -f "$ROOT/fly/fly.toml.bak"

echo "==> Patching GitHub workflow APP_NAME"
sed -i.bak "s/APP_NAME: .*/APP_NAME: ${APP_NAME}/" "$ROOT/.github/workflows/deploy.yml"
rm -f "$ROOT/.github/workflows/deploy.yml.bak"

echo "==> Creating Fly app (no deploy yet)"
fly apps create "$APP_NAME" 2>/dev/null || echo "App may already exist"

echo ""
echo "Done. Next steps:"
echo "  1. Commit and push fly/ + deploy.yml to main"
echo "  2. fly tokens create org -o personal -n github-actions-deploy"
echo "     → gh secret set FLY_API_TOKEN --env production (no trailing newline)"
echo "  3. Merge to main — deploy job rolls out the app"
echo ""
echo "  URL: https://${APP_NAME}.fly.dev"
