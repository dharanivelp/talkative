# Talkative

The project folder is named `Talkative`; Compose names the application container `talkative` and its Redis container `talkative-redis`.

## Plan layout
- User plane: Flask account and chat routes in `talkative_backend/backend`.
- Core plane: auth, authorization, eligibility, moderation, and accounting helpers in `talkative_backend/core`.
- User-data plane: private profile/authentication SQLite store in `users.db`.
- Live-chat plane: Redis queue, active `dm...` sessions, message stream, and typing state.
- Admin plane: separately protected admin routes and `admin.db`; ended session metadata and transcript expire 24 hours after ending.
- Frontend: `app/templates/index.html` and `app/static/style.css`.

User IDs are private opaque identifiers. User APIs do not return another participant's ID. Admin credentials are configured separately from user accounts.

## Configure and run
1. `cp .env.example .env`
2. Set unique strong values for `SESSION_SECRET`, `ADMIN_PASSWORD`, and `REDIS_PASSWORD` in `.env`.
3. Set `APP_ENV=development` locally to use fixed signup/login verification code `123456`. Do not use this in production. Compose defaults to `production`, which disables signup and login until email OTP delivery is implemented.
4. Start the app and Redis together with `docker compose up --build`.
5. Open `http://127.0.0.1:8000`; admin history is at `/admin`.

The app requires Redis. Do not run `python app.py` by itself unless a Redis server is already available at `REDIS_URL`.

Legacy accounts are copied from `DATABASE_PATH` to the user database on startup; old match preferences are not migrated. Configure TLS, CSRF protection, login rate limits, and real email verification before public deployment.

For AIC Docker Deploy App setup, see [AIC_DEPLOY.md](AIC_DEPLOY.md). The app image requires a separately reachable Redis service and persistent storage for SQLite database files; AIC must provide a Docker-capable runtime.
