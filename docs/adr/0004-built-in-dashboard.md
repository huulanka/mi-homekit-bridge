# 4. Built-in web dashboard

- Status: accepted
- Date: 2026-11-03

## Context

The history from [ADR 3](0003-local-history-in-sqlite.md) should be explorable as
charts (daily course, months, a year, indoor vs. outdoor) on a phone and a laptop,
reachable only from the owner's tailnet. It must run on the Raspberry Pi without a
second service, look modern and stay maintainable.

## Options

1. **Grafana**: powerful, but a separate service with its own users, plugins and
   upgrades (~150 MB RAM), SQLite only via a community plugin, and a generic look
   that is awkward on phones.
2. **Server-rendered pages** (templates + a chart library): no build step, but
   interactive charts end up as JavaScript anyway.
3. **Static single-page app bundled into the Python package**, served by the
   aiohttp server that is already a dependency, plus a small read-only JSON API.

## Decision

Option 3. The frontend uses React, TypeScript, Tailwind CSS and Apache ECharts, built
with Vite. The build output is written into `src/mi_homekit_bridge/static/`, shipped
in the wheel and pre-compressed (Brotli/gzip), so the Pi needs no Node.js. The server
binds to localhost by default; access control and HTTPS come from a reverse proxy
(`tailscale serve`). Aggregation happens in SQL; the API returns at most a few
hundred points per series.

## Consequences

- Still one service and one deployment. The dashboard can be switched off.
- Building the package now needs Node.js (CI and `scripts/deploy.sh` do it); a
  minimum version is enforced via `engines` + `engine-strict`.
- The JavaScript bundle is ~240 KB (Brotli), cached as immutable after the first load.
- Chart colors use a palette validated for color-vision deficiencies; every chart has
  a table view.
