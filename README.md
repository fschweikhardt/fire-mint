---
title: Fire Mint Retirement Projection App
emoji: 🐳
colorFrom: purple
colorTo: gray
sdk: docker
app_port: 7860
---

# Fire Mint Retirement Projection App

A simple Gradio-based retirement projection tool. Runs in Docker via docker compose.

## Run

```bash
docker compose up --build
```

Then open `http://localhost:7860` in your browser.

## Deploy on Fly.io

One-time setup (requires [flyctl](https://fly.io/docs/flyctl/install/) and `gh`):

```bash
fly auth login
APP_NAME=fire-mint ./scripts/bootstrap-fly.sh
```

Commit the patched `fly/fly.toml` and `.github/workflows/deploy.yml`, then add a Fly org token to the GitHub **production** environment:

```bash
fly tokens create org -o personal -n github-actions-deploy
gh secret set FLY_API_TOKEN --env production --repo fschweikhardt/fire-mint
```

Pushes to `main` run CI and deploy via GitHub Actions. The app URL is `https://fire-mint.fly.dev` (or your chosen `APP_NAME`).

## Inputs
- Annual contributions: SIMPLE IRA, ROTH IRA, HSA, 529, and two current savings buckets (taxable and not taxed)
- Select expected annual return: 3%, 5%, or 7% (one at a time)
- Start age (default 40) to end age (100)

## Notes
- Output table shows yearly balances per account and totals. "Already have" is last year's total (previous row's total with interest).
