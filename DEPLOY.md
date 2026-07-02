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
topictracker.example.org {
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
