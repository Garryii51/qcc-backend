# Quality Command Centre — Database Setup

Architecture: **Browser (HTML) → Flask API → Supabase**. The Supabase secret
(service-role) key lives only on the Flask server. The browser never sees it.

```
quality-tracker.html  →  fetch()  →  Flask /api/records  →  Supabase records table
```

---

## 1. Supabase — create the table (one time)

1. Create a project at supabase.com (or use your existing Command Centre project).
2. Open **SQL Editor → New query**, paste the contents of `schema.sql`, click **Run**.
3. Go to **Project Settings → API** and copy two things:
   - **Project URL**  (e.g. `https://abcd1234.supabase.co`)
   - **service_role** key under *Project API keys* — this is SECRET.

---

## 2. Flask backend

### Run locally (to test)
```cmd
cd qcc-backend
pip install -r requirements.txt
set SUPABASE_URL=https://YOUR-ref.supabase.co
set SUPABASE_SERVICE_KEY=your-service-role-key
set ALLOWED_ORIGINS=*
python app.py
```
Server runs at `http://localhost:5000`. Test it: open `http://localhost:5000/api/health`
— you should see `{"ok": true, "configured": true}`.

### Deploy on Render (same as Heat Load Calculator)
1. Push the `qcc-backend` folder to a GitHub repo.
2. Render → **New → Web Service** → connect the repo.
3. Settings:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app`
4. **Environment** tab → add:
   - `SUPABASE_URL` = your project URL
   - `SUPABASE_SERVICE_KEY` = your service-role key
   - `ALLOWED_ORIGINS` = your front-end URL, e.g. `https://yourname.github.io`
5. Deploy. Note the service URL, e.g. `https://qcc-backend.onrender.com`.

---

## 3. Front-end

Open `quality-tracker.html` and edit ONE line near the top of the `<script>`:

```js
const API_BASE = 'http://localhost:5000';   // local testing
// const API_BASE = 'https://qcc-backend.onrender.com';   // production
```

Set it to your Render URL, then host the file on GitHub Pages (or open locally
while the Flask server runs).

---

## How it behaves
- **Sr. No.** is assigned by the server (max existing + 1, per category) — consistent across all users.
- All category fields are stored in the `data` jsonb column, so adding/renaming a
  field only means editing the `CATEGORIES` object in the HTML — no DB migration.
- Adding a new category later = no schema change at all.

## Security notes
- The service-role key is only in Render's environment variables, never in git or the browser.
- A `.gitignore` is included so `.env` files can't be committed. Only `.env.example` is tracked.
- RLS is enabled with no policies, so even if the public anon key leaked it gives zero access.
- Set `ALLOWED_ORIGINS` to your real front-end URL in production (e.g. `https://yourname.github.io`), not `*`. The server logs a warning if it's left open.
- Flask debug mode is OFF by default. For local debugging only, set `FLASK_DEBUG=1`. Never set it in production.
- On Render the app runs under gunicorn (`gunicorn app:app`), which ignores debug mode regardless.

## Cold starts (Render free tier)
The free tier sleeps after ~15 min idle; the first request then takes 30–50s to wake.
The front-end handles this automatically: it shows a "Connecting to server…" overlay
and retries, so a cold start looks like loading rather than an error. Upgrade to a paid
Render instance to remove the sleep entirely.
