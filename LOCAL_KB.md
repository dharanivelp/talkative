# Talkative Local Knowledge Base (Low-Token)

## Architecture
- Entry: `app.py` -> app factory in `talkative_backend/application.py`.
- Project: folder `Talkative`; Compose project/image/container are named `talkative` (`talkative` app container, `talkative-redis` service container).
- User frontend: `app/templates/index.html`, `app/static/style.css`.
- User/auth API: `talkative_backend/backend/auth.py`; chat API: `talkative_backend/backend/chat.py`; admin API: `talkative_backend/backend/admin.py`.
- Core policy/auth/accounting helpers: `talkative_backend/core/functions.py`.
- User data plane: `talkative_backend/planes/user_store.py` -> `users.db` (PII, password hashes, unique usernames/emails, country, private `usr_...` IDs, blocks), file mode 0600.
- Live chat plane: `talkative_backend/planes/redis_chat_store.py` -> Redis (queue, active `dm...` sessions, transient messages and typing).
- Admin plane: `talkative_backend/planes/admin_store.py` -> `admin.db` (participant IDs, session metadata, ended transcript and audit events); ended records expire after 24h.
- DB/secret paths and Redis credentials: `talkative_backend/config.py`; Docker: `docker-compose.yml` + `Dockerfile`.
- Compose uses Talkative volume names; a one-shot migration service copies existing data from the previous volume names on first startup. Stop the old Compose stack before its first startup with the updated file.
- Legacy source DB: `stranger_chat.db`; startup migration copies accounts to user DB when found. Existing legacy IDs are not exposed.

## UI Notes
- Brand banners and 64x64 favicons live in `app/static/logo/`; banner variants follow the in-app theme, while favicon variants follow browser `prefers-color-scheme`.
- Reusable gender icons live in `app/static/icons/male.svg` and `app/static/icons/female.svg`; `app/static/peer-icons.css` applies them to chat and participant preview badges.
- Both main and account pages include the canonical 54px compact sticky header from `app/templates/_header.html`, keeping the enlarged logo, online count, theme toggle, and profile icon consistent; Account reveals the online/profile controls after authentication. Opening the profile from a chat preserves and restores the active conversation on return while account presence is refreshed. Profile load errors stay visible in-page; Back to chat is at the right of the account title.
- Account settings are served at `/account` from `app/templates/account.html` with Account and Settings tabs; logout is under Account, while password change and account deletion are under Settings. The Account tab has an optional bio and profession (32 characters max each), an education level selected from grouped global school, vocational, undergraduate, postgraduate, and doctoral options, and a country-specific state/region location selector, each with an independent participant-visibility checkbox defaulting off.
- `/terms` and `/privacy` provide policy drafts linked in the shared footer; signup requires explicit acceptance and stores the accepted version and timestamp.
- The Account tab shows the combined name, read-only gender, inline participant-preview link, editable username, and one score/streak badge with visible captions. Chat and participant preview show first name only; peer badges remain icon-and-number-only with a color-banded score.
- Chat peer/match payloads include name, age category, gender, home-country code/name, score, current streak, plus only optional profile fields explicitly enabled by that participant. Usernames, email, date of birth, phone, and unchecked fields remain private.
- A streak day is one authenticated presence day in UTC; repeated pings count once, consecutive active dates increment, and a missed date resets the current streak.
- Chat toolbar shows an icon-only message-sound toggle, three-dot Report/Block menu, and red End chat action; controls stay right-aligned on mobile. Participant first name appears above a row of age/country and score/streak badges.
- Only an active chat has an enabled End chat action; it stays disabled through the pre-chat briefing. During matching, Find someone becomes Cancel and the status displays elapsed seconds. Ending an active chat starts the five-second countdown without a confirmation dialog.
- Chat share exports messages visible in the current scroll viewport as a branded PNG with larger text, peer gender and visible profile details; it uses native file sharing when supported and downloads otherwise.
- Chat toolbar uses an icon toggle for message sounds, an End chat action, and a three-dot menu for Report/Block; no sound-test action is shown.
- Signup collects a home country and verifies email ownership by OTP before account creation; email is unique case-insensitively. Phone numbers are not collected.
- Country is required at signup; account/chat views no longer show a “Not provided” country placeholder.
- Typing-bubble skeleton styles live in `app/static/chat-live.css`; dark-theme overrides and theme logic are in `app/static/theme.css` and `app/templates/index.html`.

## KB Practice
- Consult this file first, including for broad or high-intensity tasks, as a low-token project map; inspect only relevant implementation files as needed.
- Keep it concise and update verified architecture, contracts, operations, UI conventions, or risks when they change.

## Contracts
- Sign-up requires first and last name, unique username, email, date of birth (ISO date), gender, home country, phone, and >=12 char password. Account shows full name; chat and participant preview show first name only. Username is distinct from email; login remains email-based. No match-gender setting.
- `/api/profile` accepts username changes and optional bio/profession/education/location values with per-field `show_*` flags; gender, name, email, date of birth, home country, and phone remain immutable after signup. Participant responses include only enabled non-empty optional values.
- Score is an integer on a 0-100 scale; `/api/score` returns chat time, moderation-event count, and reports received for the account breakdown.
- Usage streak counts authenticated presence once per UTC day; consecutive days increment the current streak, and a missed day resets it.
- Usernames are not shown to other participants; keep them out of all peer-facing API responses.
- Browser sees own/private session state only; API message rows contain `mine`, not sender/participant user IDs.
- Auth session roles are `user` and `admin`; admin endpoints must check `admin_authorized()`.
- Chat text exists in Redis while active. On end it is archived with session/participant IDs to admin DB, then removed from Redis. Admin archive is purged based on ended time after 24h.
- Core routes: `/account`, `/api/auth/signup`, `/api/auth/login`, `/api/profile`, `/api/me`, `/api/score`, `/api/match`, `/api/messages/<dm-id>`, `/api/typing/<dm-id>`, `/api/leave`, `/admin`.
- Legal routes: `/terms`, `/privacy`.

## Run / Validate
- Install: `.venv/bin/python -m pip install -r requirements.txt`.
- Local app requires Redis at `REDIS_URL`; use Compose to provide Redis: `docker compose up --build`.
- Admin configuration: `ADMIN_USERNAME`, required `ADMIN_PASSWORD`, `SESSION_SECRET` in root `.env`.
- Local signup and login use development-only fixed OTP `123456`; Compose defaults to `APP_ENV=production`, which disables both until real email delivery is implemented.
- Do not start servers unless the user asks. Focused tests should use temporary SQLite paths and a Redis mock/test instance.

## Risks / Gaps
- Admin password is an environment secret; use a long unique value. Admin login rate limiting and CSRF protection remain to be added before public deployment.
- User emails are not verified; password recovery is not implemented.
- Redis live messages are lost if Redis storage is cleared before a chat ends; Redis Compose volume enables AOF persistence.