# Talkative

The project folder is named `Talkative`; the app uses SQLite for persistence.

## Plan layout
- User plane: Flask account and chat routes in `talkative_backend/backend`.
- Core plane: auth, authorization, eligibility, moderation, and accounting helpers in `talkative_backend/core`.
- User-data plane: private profile/authentication SQLite store in `users.db`.
- Live-chat plane: SQLite-backed queue, active `dm...` sessions, message stream, and typing state.
- Admin plane: separately protected admin routes and `admin.db`; ended session metadata and transcript expire 24 hours after ending.
- Frontend: `app/templates/index.html` and `app/static/style.css`.

User IDs are private opaque identifiers. User APIs do not return another participant's ID. Admin credentials are configured separately from user accounts.

## Configure and run
1. `cp .env.example .env`
2. Set unique strong values for `SESSION_SECRET` and `ADMIN_PASSWORD` in `.env`.
3. Set `APP_ENV=development` locally to use fixed signup/login verification code `123456`. Do not use this in production. Compose defaults to `production`, which disables signup and login until email OTP delivery is implemented.
4. Start the app with `docker compose up --build` or `python app.py`.
5. Open `http://127.0.0.1:8000`; admin history is at `/admin`.

Set `PUBLIC_SITE_URL` to the canonical HTTPS domain when it differs from `https://talkative.space`. Production serves `robots.txt` and a sitemap for the public home, terms, and privacy pages; development sends `noindex` and blocks crawling.

The chat state database path is configured with `STATE_DATABASE_PATH`. For production, place it on persistent storage.

Legacy accounts are copied from `DATABASE_PATH` to the user database on startup; old match preferences are not migrated. Configure TLS, CSRF protection, login rate limits, and real email verification before public deployment.

For AIC's native Python Deploy App setup, see [AIC_DEPLOY.md](AIC_DEPLOY.md). Use a persistent disk and a single app instance; SQLite state is not suitable for multiple hosts.
