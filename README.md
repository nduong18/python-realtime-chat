# Python Realtime Chat (Flask + Socket.IO)

Simple realtime chat app using Flask and Flask-SocketIO. Ready to deploy on Render.

## Local development

1. Create and activate a virtual environment (Windows PowerShell):

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run locally:

```powershell
# dev
python app.py
# or using gunicorn for production-like
gunicorn -k eventlet -w 1 app:app
```

4. Open http://localhost:5000

## Deploy to Render

- Create a new Web Service on Render and link your repo.
- Use `render.yaml` or set the start command to:

```
gunicorn -k eventlet -w 1 app:app
```

- Set environment variable `SECRET_KEY` in Render dashboard for production.

### Database (PostgreSQL)

This app supports PostgreSQL (recommended for Render) via the `DATABASE_URL` environment variable.

- On Render, if you provision a PostgreSQL instance (Internal DB), set `DATABASE_URL` to the Internal connection string. Example:

```
DATABASE_URL=postgresql://chatuser:lMYdRgXlwgdLUWRouYlcp4ejfWnAsAcp@dpg-d3r4tf8dl3ps73cdle3g-a/chatdb_y9kn
```

- Locally, you can also set `DATABASE_URL` to point to your local Postgres. If not set, the app falls back to a local SQLite file `chat.db`.

Notes:

- If your provider gives a URL starting with `postgres://`, it will be normalized to `postgresql://` automatically.
- On first run, tables are created automatically. The app contains a small SQLite-only migration to add `password_hash` if you had a very old local DB.
