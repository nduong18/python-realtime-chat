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
