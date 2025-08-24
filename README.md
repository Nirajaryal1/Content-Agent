"""
Veo Runner Web UI — FastAPI + ChatGPT + Veo v3
===============================================


Single-file app that gives you a tiny web UI:
- Enter one **master prompt** (+ optional style/seed/settings)
- Click **Generate** → uses **ChatGPT** to create 10 scene prompts
- (Optional) **Render** all scenes with **Veo v3** and **Concatenate** with FFmpeg
- Shows JSON + Markdown of prompts and download links to resulting MP4 files


Run
----
1) Install deps:
pip install fastapi uvicorn jinja2 openai google-genai python-multipart
# If you use Vertex AI instead of AI Studio, install google-cloud-aiplatform and auth


2) Set keys (pick ONE Veo backend):
export OPENAI_API_KEY=sk-...
# A) Google AI Studio
export GOOGLE_API_KEY=AIza...
# B) Vertex AI
export GOOGLE_CLOUD_PROJECT=your-project-id
export GCP_LOCATION=us-central1
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json


3) Start the server:
uvicorn app:app --reload --port 7860


Open http://localhost:7860


Notes
-----
- This is synchronous for simplicity. Rendering 10 clips will take a while in one request.
- If you want background jobs + progress bars, we can add a task queue (RQ/Celery) or SSE.
"""
