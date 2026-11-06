# Clarivue AI — Deployment Guide (preparation only, not yet deployed)

Stack: MongoDB Atlas + Render (backend) + Vercel (frontend).

## 1. MongoDB Atlas
1. Create a free (M0) cluster, a database user, and allow network access (0.0.0.0/0 for Render, or Render's static IP if on a paid plan).
2. Copy the `mongodb+srv://...` connection string — this is `MONGODB_URI`.
3. No code changes needed; `dnspython` (required for `+srv` URIs) is now pinned in `requirements.txt`.

## 2. Render (backend)
- `render.yaml` (repo root) defines the service: Docker runtime, `backend/Dockerfile`, health check `/health`, and a 1GB persistent disk mounted at `/var/data`.
- Set `STORAGE_ROOT=/var/data` (already in `render.yaml`) so uploaded guideline PDFs/brand assets/submission images survive redeploys — no code change needed, `app/core/storage.py` already reads this from settings.
- Set the `sync: false` env vars manually in the Render dashboard (never commit them): `MONGODB_URI`, `GEMINI_API_KEY`, `FRONTEND_ORIGIN`, `JWT_SECRET_KEY`.
- The Dockerfile's `CMD` now binds to Render's injected `$PORT` and no longer runs `--reload` (removed for production; local Docker dev keeps `--reload` via `docker-compose.yml`'s explicit `command:` override).

## 3. Vercel (frontend)
- Framework preset: Vite (auto-detected).
- `frontend/vercel.json` adds the SPA rewrite React Router needs (otherwise a direct link to e.g. `/submissions/abc` 404s).
- Set `VITE_API_BASE_URL` to the Render backend's URL in Vercel's project env settings.

## 4. CORS
`FRONTEND_ORIGIN` (backend) must exactly match the deployed Vercel URL — `app/main.py` already wires this into `CORSMiddleware`. No code change needed; single-origin is sufficient (set once per environment).

## 5. Required environment variables

| Variable | Used by | Production value | Secret? |
|---|---|---|---|
| `MONGODB_URI` | Backend | Atlas `mongodb+srv://...` string | **Yes** |
| `MONGODB_DB_NAME` | Backend | `clarivue_ai` | No |
| `GEMINI_API_KEY` | Backend | Your Gemini key | **Yes** |
| `GEMINI_MODEL` | Backend | `gemini-3.5-flash-lite` | No |
| `GEMINI_EMBEDDING_MODEL` | Backend | `gemini-embedding-001` | No |
| `FRONTEND_ORIGIN` | Backend (CORS) | Vercel URL | No |
| `STORAGE_ROOT` | Backend | `/var/data` (mounted disk) | No |
| `JWT_SECRET_KEY` | Backend (JWT signing, Phase 9 Stage 2) | random string | **Yes** |
| `REQUIRE_JWT_AUTH` | Backend | `true` in production | No |
| `ENABLE_DEMO_ENDPOINTS` | Backend | `false` in production | No |
| `VITE_API_BASE_URL` | Frontend | Render backend URL | No |

The Gemini key stays backend-only; nothing in `frontend/` ever reads it.

## 6. Pre-flight checklist
- [ ] `backend/.env` populated locally is **not** committed (already gitignored)
- [ ] `/health` returns `mongodb_connected: true` against the Atlas URI before first deploy
- [ ] First deploy: confirm an uploaded guideline PDF survives a manual Render restart (proves the persistent disk is actually mounted)
- [ ] Demo seed script (`python -m app.seed`) run once against Atlas if demo data is wanted in production

## 7. Known limitations carried over
- Real JWT login now exists (Phase 9 Stage 2, `POST /api/auth/login`), but most existing users were seeded without a password and cannot log in until one is set directly in the database — there is no self-signup/password-set endpoint yet.
- Logout is a client-side token discard only; there is no server-side token blocklist, so a leaked token remains valid until it expires (`JWT_EXPIRE_MINUTES`).
- Only `REQUIRE_JWT_AUTH=true` actually closes the demo-header bypass — if left `false` in production, anyone can still impersonate any seeded user exactly as before. This must be set explicitly.
