# Deploying Talkative as a Docker app on AIC

AIC must provide a Docker/container deployment runtime for this option. Select
Docker as the app runtime and build from this repository's `Dockerfile`. The
Docker image contains the Talkative web app only; Redis is a separate service.
This app deployment does not automatically start the Redis or migration
services in `docker-compose.yml`.

## Configure the AIC app

Connect the personal repository and select branch `deploy-test`. Choose the
Docker/container runtime, not the native Python buildpack. The Dockerfile starts
Gunicorn on AIC's `PORT` environment variable, defaulting to port `8000`. If the
dashboard requires an internal port, configure it to match `PORT` (or `8000`
when AIC does not assign one).

The deployment log previously reported that Docker was unavailable and fell
back to the native buildpack. If AIC continues to show that message, the current
Deploy App host cannot build this Dockerfile; no repository change can enable
Docker on that host. Ask AIC support to enable Docker for the app or use a
Docker-capable AIC service/VPS.

Configure these environment variables in AIC's app settings; do not commit
secrets or put them in the build command:

| Variable | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `SESSION_SECRET` | A newly generated, high-entropy secret |
| `ADMIN_USERNAME` | The admin account name |
| `ADMIN_PASSWORD` | A new, unique admin password |
| `REDIS_URL` | Reachable Redis endpoint, e.g. `rediss://HOST:PORT/0` when TLS is supported |
| `REDIS_PASSWORD` | Redis credential, if required by the provider |
| `USER_DATABASE_PATH` | `/data/users.db` on the persistent mount |
| `ADMIN_DATABASE_PATH` | `/data/admin.db` on the persistent mount |
| `DATABASE_PATH` | `/data/talkative.db` on the persistent mount, if migrating one |

Use the exact Redis hostname, port, TLS scheme, and authentication settings
provided by the Redis host. Do not use `127.0.0.1` unless Redis runs in the same
runtime. The app checks Redis during startup and will exit if it cannot connect.
An error such as `Error 111 connecting to 127.0.0.1:6379` means `REDIS_URL` is
unset or points to an address where Redis is not running. A Redis password by
itself is not enough; set the reachable host and port too.

Attach an AIC persistent disk or volume at `/data`. Without persistent storage,
SQLite account and admin data can be lost when the app is replaced or restarted.
Back up that storage securely.

## Before accepting users

The current app intentionally fails closed for signup and login in production
until real email OTP delivery is implemented and configured. Do not set
`APP_ENV=development` on a public deployment; development mode uses a fixed
verification code. Also configure HTTPS and rotate any credentials that have
previously been exposed.
