# Deploying Talkative with AIC Deploy App

AIC's native Python buildpack can run the Talkative web process using the
`Procfile` in this repository. This deployment does not run `docker-compose.yml`;
Redis must be provided separately and reachable from the app.

## Configure the AIC app

Connect the repository and branch `deploy-test`. Set the build command to
`pip install -r requirements.txt` if AIC does not install dependencies
automatically. Set the web start command to the `web:` command in `Procfile` if
AIC does not detect Procfile processes:

```sh
gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 app:app
```

If deployment logs still say `Starting Python app (app.py)`, AIC is using its
automatic entry point rather than the Procfile. Configure the command above in
the app's start-command setting if available. The startup command does not
provide Redis; configure the Redis environment variables below separately.

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
| `USER_DATABASE_PATH` | `users.db` path under AIC's persistent mounted storage |
| `ADMIN_DATABASE_PATH` | `admin.db` path under AIC's persistent mounted storage |
| `DATABASE_PATH` | Legacy database path under persistent storage, if migrating one |

Use the exact Redis hostname, port, TLS scheme, and authentication settings
provided by the Redis host. Do not use `127.0.0.1` unless Redis runs in the same
runtime. The app checks Redis during startup and will exit if it cannot connect.
An error such as `Error 111 connecting to 127.0.0.1:6379` means `REDIS_URL` is
unset or points to an address where Redis is not running. A Redis password by
itself is not enough; set the reachable host and port too.

Enable a persistent disk or mounted volume in AIC and point the three database
path variables to that mount. The mount path is provider-specific. Without
persistent storage, SQLite account and admin data can be lost when the app is
replaced or restarted. Back up that storage securely.

## Before accepting users

The current app intentionally fails closed for signup and login in production
until real email OTP delivery is implemented and configured. Do not set
`APP_ENV=development` on a public deployment; development mode uses a fixed
verification code. Also configure HTTPS and rotate any credentials that have
previously been exposed.
