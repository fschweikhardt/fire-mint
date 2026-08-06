---
title: Fire Mint Retirement Projection App
emoji: 🐳
colorFrom: purple
colorTo: gray
sdk: docker
app_port: 7860
---


# Fire Mint Retirement Projection App

A Gradio-based retirement and education projection tool. Runs in Docker via docker compose.

## Run

```bash
docker compose up --build --watch
```

`--watch` restarts the app when `app.py` changes (bind mount keeps the file in sync; restart reloads Python). Without `--watch`, use `docker compose up --build` and restart manually after edits.

Then open `http://localhost:7860` in your browser.

## QR page (`/qr`)

Open [`/qr`](http://localhost:7860/qr) to show a scannable QR code for this site (encodes the site root, not `/qr`). The page lives in [`qr/index.html`](qr/index.html)—copy the whole `qr/` folder into other projects:

- **nginx + static frontend:** `frontend/public/qr/index.html` (served at `/qr` automatically)
- **FastAPI / Gradio:** serve the same file at `GET /qr` (see `register_qr_route` in `app.py`)

Optional: set `<meta name="qr-target" content="https://example.com/">` when serving if you need a fixed canonical URL.

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

- **Accounts:** Taxable, Roth IRA, and HSA — each with current balance, annual contribution, and optional yearly step-up amount
- **529:** Current balance, annual contribution, and its own growth rate
- **Horizon:** Start age, retire age (contributions stop), end age
- **Assumptions:** Growth rate (0–14%), inflation, today’s-dollars toggle, fixed-income yield rate
- **FIRE:** Desired annual spend and withdrawal rate (nest egg = spend ÷ rate)

## Outputs

- **At a glance:** Nest egg and simple yield at key ages, FIRE hit age, $1M milestone
- **Chart:** Taxable / Roth / HSA / Total balances over time
- **Tabs:** Year-by-year retirement table, fixed-income table, 529 table, assumptions notes
- **CSV:** Download of the full projection

## Notes

- Each year: `balance = balance × (1 + r) + contribution` (end-of-year contribution convention)
- **TOTAL** is the sum of Taxable + Roth + HSA only (do not add ANNUAL IN again; 529 is separate)
- **Simple yield** on the Income tab is `total × rate` — illustrative only, not a tax-aware Safe Withdrawal Rate
- Roth/HSA contribution limit hints are informational; the app does not enforce IRS caps
