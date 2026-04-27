# NexusRAG Dashboard

Next.js 14 dashboard for the NexusRAG multi-tenant RAG platform. Calibrated
for a Vercel-grade aesthetic — restrained neutral surfaces, a single brand
accent fired sparingly, ruthless typography discipline, and live data pulled
from the FastAPI BFF.

## Stack

- **Next.js 14** (App Router, RSC, route groups)
- **TypeScript** (strict mode, `tsc --noEmit` clean)
- **Tailwind CSS 3** with a hand-rolled token system — three border weights,
  three text tiers, semantic colours scoped to status/state only
- **Geist Sans + Geist Mono** as the canonical typography stack
- **Radix UI** primitives for menus, dialogs, popovers, scroll areas, tabs,
  tooltips, dropdowns, avatars
- **cmdk** for the ⌘K command palette
- **sonner** for toast notifications
- **next-themes** for light / dark / system theming
- **recharts** for the telemetry chart surface
- **framer-motion** primitives for page transitions and entrance animations
- **vitest + Testing Library** for unit/component tests (36 tests, 6 files)

## Routes

| path | what it shows |
|---|---|
| `/` | Overview — live KPI tiles wired to the public `/api/stats` contract, platform status row, quota widget, activity feed |
| `/telemetry` | Polling Tier-A telemetry consumer — full metric grid, raw JSON inspector, contract docs, 30s visibility-aware polling |
| `/documents` | Searchable, filterable, paginated documents table; reindex with optimistic update + toast |
| `/run` | Live `/v1/run` chat with token streaming, abort, and auto-grow textarea |
| `/api-keys` | Active key + curl/TypeScript usage examples |
| `/settings` | Theme, workspace identity, entitlements, resources |
| `/_not-found`, `/error`, `/loading` | Polished states for every route |

## Design system

Single source of truth for tokens lives in `src/app/globals.css`:

```
--background, --surface, --surface-2, --surface-3       /* 4 surface tiers */
--foreground, --foreground-muted, --foreground-subtle,
--foreground-faint                                      /* 4 text tiers */
--border, --border-strong, --border-subtle              /* 3 border weights */
--brand, --brand-strong                                 /* sparingly */
--success, --warning, --danger, --info                  /* status only */
--radius-sm/md/lg/xl                                    /* tight 4/6/8/12 */
```

Tailwind extends these in `tailwind.config.ts` so every component reads from
the same source. Dark mode (`[data-theme="dark"]`) is the default; light mode
is plumbed through `next-themes` and follows the same token system.

## Live data wiring

The dashboard reads from two surfaces of the FastAPI BFF, both proxied
through Next.js rewrites:

- `/api/stats` — public Tier-A telemetry endpoint (no auth). Source of
  truth for KPI tiles on `/` and the entire `/telemetry` page. See the
  shared schema at
  https://github.com/IgnazioDS/IgnazioDS/blob/main/TELEMETRY_SCHEMA.md
- `/api/ui/*` — versioned BFF endpoints (Bearer auth). Bootstrap, dashboard
  summary, documents, activity, reindex actions

The rewrite map lives in `next.config.mjs` and resolves the upstream from
`NEXT_PUBLIC_API_BASE` (or `NEXUSRAG_API_URL`), defaulting to
`https://nexusrag-lyart.vercel.app`.

## Local development

```bash
cd frontend
npm install
NEXT_PUBLIC_API_KEY=<your-bearer-token> npm run dev
```

The app boots at http://localhost:3000. The `/api/stats` page works without
an API key (public contract). Other pages need a valid Bearer key.

## Scripts

| command | what it does |
|---|---|
| `npm run dev` | Local dev server with hot reload |
| `npm run build` | Production build (Next.js output) |
| `npm run start` | Run the production build locally |
| `npm run lint` | Next.js ESLint |
| `npm run type-check` | `tsc --noEmit` |
| `npm test` | Run the vitest suite once |
| `npm run test:watch` | Watch-mode test runner |

## Tests

```
$ npm test

✓ src/lib/utils.test.ts                (15 tests)
✓ src/lib/hooks.test.ts                (4 tests)
✓ src/components/ui/button.test.tsx    (6 tests)
✓ src/components/ui/sparkline.test.tsx (5 tests)
✓ src/components/ui/badge.test.tsx     (3 tests)
✓ src/components/dashboard/StatCard.test.tsx (3 tests)

Tests:    36 passed (36)
Duration: ~1.1s
```

Run `npm run test:watch` for development; tests use `vitest` + jsdom +
`@testing-library/react`.

## Keyboard shortcuts

| keys | action |
|---|---|
| ⌘K / Ctrl+K | Open command palette |
| G then O | Go to Overview |
| G then T | Go to Telemetry |
| G then D | Go to Documents |
| G then R | Go to Try It |
| Esc (in palette) | Close |

## Deployment

The frontend is a self-contained Next.js app. To deploy as a separate Vercel
project:

1. Create a new Vercel project from `IgnazioDS/NexusRAG`.
2. Set **Root Directory** to `frontend`.
3. Framework Preset: **Next.js** (auto-detected).
4. Environment variables (all scopes):
   - `NEXT_PUBLIC_API_BASE` = `https://nexusrag-lyart.vercel.app`
   - `NEXT_PUBLIC_API_KEY` = your tenant's Bearer token (only needed for
     authenticated pages; the `/api/stats` page works without it)

The included `vercel.json` already pins the `nextjs` framework preset, build
command, and output directory, so the project import is one click.

## Architecture notes

- **State management** is intentionally local. No global store; pages own
  their own data via `useEffect` + the typed fetchers in `src/lib/api.ts`.
  Telemetry uses `usePolling()` (visibility-aware, 30s interval).
- **Animations** are driven by Tailwind keyframes (`fade-up`, `scale-in`,
  `pulse-ring`, `shimmer`) plus a small `useAnimatedNumber` hook for the
  count-up on KPI tiles. framer-motion is available but used sparingly —
  most motion is CSS.
- **Accessibility**: all interactive primitives are Radix-based and ship
  with proper ARIA attributes. Focus rings, keyboard navigation, and
  contrast were verified against WCAG AA on the dark theme.
- **Bundle size**: First Load JS is ~150kB across all routes. The
  `optimizePackageImports` in `next.config.mjs` ensures lucide and recharts
  tree-shake correctly.
