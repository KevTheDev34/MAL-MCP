# MAL OAuth Setup

Connect a MyAnimeList account to the local assistant. Tokens stay on the
server: they are encrypted at rest and never returned to the browser, logs, or
LLM context.

## 1. Register a MAL API application

1. Open [MyAnimeList API client configuration](https://myanimelist.net/apiconfig).
2. Create a new client / application.
3. Set **App Redirect URL** to exactly the same value as `MAL_REDIRECT_URI`
   (default for local development: `http://localhost:8000/auth/mal/callback`).
4. Copy the **Client ID** and **Client Secret**.

## 2. Configure environment variables

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Purpose |
|---|---|
| `MAL_CLIENT_ID` | Client ID from MAL |
| `MAL_CLIENT_SECRET` | Client secret from MAL |
| `MAL_REDIRECT_URI` | Must match the redirect URL registered with MAL |
| `TOKEN_ENCRYPTION_KEY` | Fernet key used to encrypt tokens at rest |

Generate an encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Optional tuning:

| Variable | Default | Purpose |
|---|---|---|
| `OAUTH_STATE_EXPIRATION_MINUTES` | `10` | OAuth `state` TTL |
| `TOKEN_REFRESH_SKEW_SECONDS` | `60` | Refresh access tokens this many seconds before expiry |
| `REQUEST_TIMEOUT_SECONDS` | `15` | HTTP timeout for MAL calls |

**Never commit `.env`.** Never paste access tokens, refresh tokens, or client
secrets into issues, chat, or logs.

## 3. Migrate and run

```bash
pip install -e ".[dev]"
alembic upgrade head
uvicorn backend.app.main:app --reload --port 8000
```

Docker Compose reads the same variables from the host environment / `.env`:

```bash
docker compose up --build
```

## 4. Connect MAL

1. Open `http://localhost:8000/auth/mal/start` in a browser.
2. Authorize the application on MyAnimeList.
3. MAL redirects to `/auth/mal/callback`. On success you receive JSON with
   `connected: true` and your MAL username (no tokens).
4. Verify:

```bash
curl -s http://localhost:8000/auth/mal/status
```

Example connected response:

```json
{
  "connected": true,
  "provider": "mal",
  "mal_user_id": "123456",
  "mal_username": "example",
  "token_expires_at": "2026-08-04T16:00:00+00:00",
  "reconnect_required": false
}
```

## 5. Disconnect

```bash
curl -s -X POST http://localhost:8000/auth/mal/disconnect
```

This deletes stored encrypted credentials for the local user.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/auth/mal/start` | Begin OAuth; 302 to MAL |
| `GET` | `/auth/mal/callback` | OAuth callback; stores encrypted tokens |
| `GET` | `/auth/mal/status` | Connection status (no tokens) |
| `POST` | `/auth/mal/disconnect` | Remove stored credentials |

## Security notes

- OAuth `state` is single-use and expires.
- PKCE uses MAL’s supported `plain` method.
- Access and refresh tokens are Fernet-encrypted in SQLite.
- Automatic refresh runs when an access token is near expiry; failed refresh
  clears tokens and sets `reconnect_required`. Transient network/5xx refresh
  failures leave credentials intact.
- Backup `TOKEN_ENCRYPTION_KEY` separately from the database. Losing the key
  makes stored tokens unreadable (reconnect MAL to recover).

## Next: MAL API client

Authenticated MAL reads and list updates use `MalClient`, which consumes
`MalOAuthService.get_valid_access_token()`. See
[`docs/mal-client.md`](mal-client.md) for the client API, retries, and the
reversible manual list-update script.
