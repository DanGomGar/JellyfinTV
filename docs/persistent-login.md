# Persistent Jellyfin login

## Purpose

JellyfinTV normally keeps its Jellyfin URL, user identity, and access token only in process memory. Enabling **Mantener JellyfinTV conectado después de reinicios** stores the successful connection in JellyfinTV's existing SQLite database so container and process restarts no longer require another password login.

This is an instance-wide connection, not a per-browser session. Every LAN client using this JellyfinTV instance shares the same backend Jellyfin connection.

## Stored data

The `jellyfinconnection` table stores a single row containing:

- Jellyfin server URL;
- username;
- Jellyfin user ID;
- Jellyfin access token;
- last update timestamp.

The Jellyfin password is never persisted and is cleared from application settings immediately after authentication. The database remains in `/app/data/jellyfintv.db`, backed by the existing `./data:/app/data` Docker volume.

## Login behavior

`POST /api/login` accepts:

```json
{
  "url": "http://192.168.100.25:8096",
  "username": "user",
  "password": "password",
  "remember": true
}
```

The URL and username are validated before authentication. Credentials are tested without changing the active connection. Only a successful login replaces the in-memory connection. If `remember` is true, the resulting token is saved; if false, any previously remembered connection is removed and the new token remains memory-only.

## Startup behavior

At startup JellyfinTV:

1. creates any missing database tables;
2. loads the remembered connection, if present;
3. configures the Jellyfin client with the stored URL, user ID, and token;
4. validates the token with Jellyfin `/Users/Me`;
5. keeps the token when Jellyfin is temporarily unavailable;
6. deletes it and returns to login when Jellyfin explicitly reports it as unauthorized.

`GET /api/auth/status` lets the administration UI determine whether it can enter automatically. It returns connection state and non-secret display fields, never the access token or password.

## Logout

`POST /api/logout` attempts Jellyfin session logout, clears the runtime client, and removes the remembered row. The next administration-page visit requires credentials again.

## Operational and security notes

- The remembered token has the permissions of the Jellyfin user that created it.
- The feature does not add per-browser authentication or access control to JellyfinTV itself.
- JellyfinTV is intended to remain LAN-only in this installation.
- Existing playback still exposes the Jellyfin token through the legacy `/now` web-watch flow; that accepted risk is not changed by this feature.
- Database files and backups under `data/` must remain outside Git.
- Replacing the database, revoking the Jellyfin token, logging out, or changing the Jellyfin user can require a new login.

## Validation checklist

1. Login with remember disabled, restart, and confirm the form returns.
2. Login with remember enabled, restart, and confirm administration opens automatically.
3. Confirm `/remote` can load current metadata and tune TV11 after restart.
4. Confirm the password is absent from the SQLite schema and data.
5. Confirm logout removes the saved row and requires credentials again.
6. Confirm a malformed URL or failed login does not replace an active valid connection.
