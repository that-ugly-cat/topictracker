# Deploying TopicTracker

TopicTracker is a single FastAPI app backed by SQLite, with per-run outputs stored as files
on disk (`data/`, `export/`). No external services.

## 1. Configuration (environment variables)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `JWT_SECRET` | **yes** | — | signs the session JWT — the app crashes on startup if unset |

Generate a secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 2. Local / bare-metal

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_md   # optional, needed for lemma analysis
cp .env.example .env                       # set JWT_SECRET
uvicorn main:app --host 0.0.0.0 --port 8000
python seed_admin.py you@example.com 'a-strong-password' 'Your Name'
```

## 3. Docker

```bash
cp .env.example .env   # set JWT_SECRET
docker compose up -d --build
docker compose exec topictracker python seed_admin.py you@example.com 'a-strong-password' 'Your Name'
```

`docker-compose.yml` maps the app to host port `8004` and mounts `./data` and `./export` as
volumes — both need to persist across rebuilds, since they hold every run's downloaded
corpus and analysis outputs.

## 4. Reverse proxy (HTTPS)

Example **Caddy**:

```
yourdomain.example {
    reverse_proxy localhost:8004
}
```

## 5. Updating

```bash
cd /opt/apps/topictracker
git pull
docker compose up -d --build
```

`data/`, `export/` and `.env` are gitignored — `git pull` never touches them.

## 6. Backups

`data/` (the SQLite DB — users and run metadata) and `export/` (every run's downloaded
corpus, CSVs, plots) are both plain files/folders — back up by copying them:

```bash
cp -r data data-backup-$(date +%F)
cp -r export export-backup-$(date +%F)
```

`export/` can get large for big corpora (tens of thousands of papers) — consider archiving
old runs elsewhere if disk space is tight.

## Authentication: two modes

TopicTracker authenticates on its own by default and needs no identity
provider. `AUTH_MODE=gateway` is a second mode, for a deployment sitting behind
an SSO gate that speaks the `X-Borant-*` header contract.

```
AUTH_MODE=local     (default)   email + password against the users table
AUTH_MODE=gateway               the upstream gate vouches via X-Borant-Sub
```

`local` is the default deliberately: an app that believes an identity header
with no gate in front of it lets anyone be anyone, so the gateway path is dead
code until someone turns it on. In `gateway` the app additionally checks the
request came from `BORANT_TRUSTED_PROXY` — under Docker that is a bridge
gateway and **not** `127.0.0.1`, and it is read off the app's log after a real
request rather than deduced from the network layout:

```
docker compose logs --tail 20 topictracker
# INFO:  192.168.x.1:54321 - "GET / HTTP/1.1" 200 OK
#        ^ that is BORANT_TRUSTED_PROXY
```

Two things that do not change in `gateway`. Local passwords stay populated,
which is what makes flipping back to `local` a working way home — a profile
born from the gate is given a random local password an admin can reset. And
`is_admin` is never granted from a header: a subject the app has never seen
gets an ordinary profile that owns no runs.

Linking existing accounts to gate subjects is a one-off manual step, run before
the mode is flipped:

```
docker exec -w /app topictracker-topictracker-1 python map_borant.py --report
docker exec -w /app topictracker-topictracker-1 python map_borant.py \
    --map you@example.org=01ABC...
```

`/healthz` answers outside any gate and reports the mode in force.

Rollback is two independent moves: `AUTH_MODE=local` plus
`docker compose up -d` restores the app as it was, and dropping the gate's
block from the reverse proxy removes the redirect to its login.
