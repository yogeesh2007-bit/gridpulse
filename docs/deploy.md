# Deploy: frontend on Vercel, backend on Render

Browser -> Vercel (React app; `/api/*` rewritten to Render, so sign-in cookies stay first-party)
Browser -> Render directly for the live WebSocket (Vercel cannot proxy WebSockets; auth is the token in the URL)

1. **Backend (Render):** New > Blueprint > pick this repo. Set `OPERATOR_INVITE_CODE` (and optionally `OPENROUTER_API_KEY`).
   Service name must be `gridpulse-api`, or edit the host in `web/vercel.json` and `web/.env.production`.
2. **Frontend (Vercel):** `cd web && vercel login && vercel --prod` (or import the repo with Root Directory = `web`).
3. Open the Vercel URL, sign up, and use your operator invite code to create an operator.

Limits: on Render's free plan the disk is ephemeral (accounts and data reset on restart) and the service sleeps after
15 idle minutes. For persistence use a paid plan with a disk mounted at `/var/data` and `GRIDPULSE_DB=/var/data/gridpulse.db`.
