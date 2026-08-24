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

## The landing, the home, and the role hint

Same shape in every app of the perimeter, so there is nothing to remember per
tool.

**`/` is a public showcase and never asks who is reading it.** Not laziness: on
the public branch of the reverse proxy the `X-Borant-*` headers are stripped by
construction, so a branch on the user is always false behind the gate and
sometimes true without one — the same page with two behaviours. By not asking,
the page is identical in both modes and one button covers all four cases:
gated or standalone, already signed in or not. It also shows no internal
counts: anyone can read it.

**The app lives at `/app`**, which is gated, and the showcase's button
points there — not at `/login`, which on a page that can never recognise anyone
would close a loop with no way in, and not at the gate's own URL, which would
work and would wire Borant ID into an app that must keep running without it.

**The role hint is honoured, and its vocabulary is one word: `admin`.** That
flag opens `/admin/users` and not the product: a non-admin creates runs
perfectly well. A profile created as an admin this way is logged loudly. An
unrecognised hint grants nothing.

**A page that needs an identity fails closed.** In `gateway` an unauthenticated
request does *not* redirect to `/login` — the app switches that route off in
this mode and sends it back, so the two would bounce forever. Production never
shows it because the gate intercepts first, but a wrong proxy matcher would
produce a spin instead of an error, and a loop is far harder to diagnose than a
status code. The answer is a 503 naming what the operator should check, because
a request arriving with no identity means the gate did not run.
