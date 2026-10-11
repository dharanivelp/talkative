# Deploying Talkative as a native Python app on AIC

Talkative uses one Flask/Gunicorn app and SQLite for user, admin, and live-chat
state. It does not need Docker, Redis, or an operating-system package manager.
The state database is shared by Gunicorn workers on the same host, so run one
app instance and attach persistent storage.

## Configure the AIC app

Connect the repository branch containing this version of the source and select
the native Python runtime. AIC should install `requirements.txt` and start
`python app.py`. This starts Gunicorn on `0.0.0.0:$PORT` (default `8000`) and
logs access and error output to the platform.

Set these environment variables in AIC's app settings:

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `GLOBAL_CHAT_SIMULATION_ENABLED` | `false` (set to `true` only while testing the simulated Global chat feed) |
| `SESSION_SECRET` | A newly generated, high-entropy secret |
| `ADMIN_USERNAME` | The admin account name |
| `ADMIN_PASSWORD` | A new, unique admin password |
| `USER_DATABASE_PATH` | `/data/users.db` |
| `ADMIN_DATABASE_PATH` | `/data/admin.db` |
| `DATABASE_PATH` | `/data/talkative.db` |
| `STATE_DATABASE_PATH` | `/data/state.db` |

Attach a persistent disk or volume at `/data`. Account records, admin history,
and chat state are SQLite files; without persistent storage they can be lost
when AIC replaces or restarts the app. Back up these files securely and test
restores. Keep the app to one instance: SQLite is not the shared database for
horizontal or multi-host scaling.

`DEMO_ONLINE_COUNT_ENABLED` only controls the demo online count in the header.
The Global chat simulator is controlled separately by
`GLOBAL_CHAT_SIMULATION_ENABLED`. When enabled, simulated messages are visible
to all visitors but remain separate from real chat history; turn it off after
testing and restart/redeploy the app for the setting to take effect.

## Before accepting users

Signup and login intentionally fail closed in production until real email OTP
delivery is implemented and configured. Do not set `APP_ENV=development` on a
public deployment; development mode uses a fixed verification code. Configure
HTTPS and rotate credentials that have previously been exposed.
