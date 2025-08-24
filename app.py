"""
Veo Runner Web UI — ChatGPT + Veo v3 (FastAPI)
- Generate 10 scene prompts with ChatGPT
- (Optional) Render each scene with Veo v3 (Google AI Studio)
- (Optional) Concat all clips into full_minute.mp4 with FFmpeg
"""

from __future__ import annotations
import os, json, time, subprocess, uuid
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Template

# ---------- Config / directories ----------
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
OUT_ROOT = Path("runs").absolute()
OUT_ROOT.mkdir(exist_ok=True)

# ---------- OpenAI / ChatGPT ----------
try:
    from openai import OpenAI
    openai_client = OpenAI()
except Exception:
    openai_client = None

PROMPT_SYSTEM = (
    "You are a film prompt director. Expand one master idea into SCENES scene-level prompts. "
    "Keep continuity (style/characters), but vary shot types, camera moves, and emotional beats. "
    "Each scene fits ~DURATION seconds. Return strict JSON with fields: scenes:[{index,title,prompt}]."
)

PROMPT_USER_TEMPLATE = (
    "MASTER: {master}\n"
    "STYLE_LOCK: {style}\n"
    "SCENES: {scenes}\n"
    "DURATION: {sec}s\n"
    "SHOT_VARIETY: ultra-wide, wide, medium, close, aerial, tracking, dolly, orbit, static.\n"
    "CAMERA_GRAMMAR: pan, tilt, dolly, crane, orbit, rack focus, parallax.\n"
    "LIGHTING: golden hour, blue hour, neon rim, volumetric fog, silhouette.\n"
    "Return JSON only."
)

def expand_scenes(master: str, style: str, scenes: int, sec: int) -> List[Dict[str, Any]]:
    if openai_client is None:
        raise RuntimeError("OpenAI client not available. Set OPENAI_API_KEY and install `openai`.")
    resp = openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": PROMPT_USER_TEMPLATE.format(master=master, style=style, scenes=scenes, sec=sec)},
        ],
        temperature=0.8,
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("scenes", [])

# ---------- Veo client (Google AI Studio) ----------
class VeoClient:
    """AI Studio path; set GOOGLE_API_KEY. Adjust model name if your account differs."""
    def __init__(self, seconds: int = 8, ar: str = "16:9", fps: int = 24, seed: Optional[int] = None):
        self.seconds = seconds
        self.ar = ar
        self.fps = fps
        self.seed = seed
        self._ensure_backend()

    def _ensure_backend(self):
        if not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError("Missing GOOGLE_API_KEY for Veo (AI Studio).")
        try:
            from google import genai  # noqa
        except Exception:
            raise RuntimeError("Install `google-genai`: pip install google-genai")

    def render(self, prompt: str, out_path: Path) -> None:
        from google import genai
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        model = "veo-3"  # change if your model name differs
        resp = client.models.generate_video(
            model=model,
            prompt=prompt,
            aspect_ratio=self.ar,
            duration_seconds=self.seconds,
            frame_rate=self.fps,
            seed=self.seed,
        )

        # Try common SDK response patterns:
        if hasattr(resp, "save"):
            resp.save(str(out_path))
            return

        url = getattr(resp, "media_url", None) or getattr(resp, "video_url", None)
        if url:
            import requests
            r = requests.get(url, timeout=600)
            r.raise_for_status()
            out_path.write_bytes(r.content)
            return

        # Some SDKs return bytes directly or an iterator:
        data = getattr(resp, "bytes", None)
        if data:
            out_path.write_bytes(data)
            return

        raise RuntimeError("Veo response did not contain a downloadable asset (check SDK/version).")

def concat_ffmpeg(mp4_paths: List[Path], out_path: Path) -> None:
    tmp = out_path.with_suffix(".list.txt")
    tmp.write_text("\n".join([f"file '{p.as_posix()}'" for p in mp4_paths]), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp), "-c", "copy", str(out_path)],
        check=True,
    )

# ---------- FastAPI app ----------
app = FastAPI()
app.mount("/runs", StaticFiles(directory=str(OUT_ROOT)), name="runs")

INDEX_HTML = Template("""
<!doctype html><html><head>
<meta charset="utf-8" /><meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Veo Runner</title>
<style>
body{font-family:system-ui,Segoe UI,Roboto;max-width:980px;margin:40px auto;padding:0 16px}
.card{border:1px solid #e5e7eb;border-radius:14px;padding:16px;margin:12px 0}
textarea,input[type=text]{width:100%;padding:10px;border:1px solid #d1d5db;border-radius:10px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
button{padding:10px 16px;border:0;border-radius:10px;background:#111827;color:#fff;cursor:pointer}
.muted{color:#6b7280}
pre{background:#0b1020;color:#d1e1ff;padding:12px;border-radius:10px;overflow:auto}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.thumb{border:1px solid #e5e7eb;border-radius:12px;padding:8px}
</style>
</head><body>
<h1>Veo Runner — ChatGPT ➜ Veo v3</h1>
<p class="muted">Enter a master prompt → get 10 scenes → optionally render with Veo and concat.</p>

<div class="card">
  <form method="post">
    <label>Master prompt</label>
    <textarea name="master" rows="4" placeholder="A lyrical travel film across the Himalayas at dawn...">{{ master or "" }}</textarea>
    <div class="row">
      <div><label>Style lock</label><input type="text" name="style" value="{{ style or "" }}" placeholder="cinematic, golden hour, smooth gimbal moves"></div>
      <div><label>Seed (optional)</label><input type="text" name="seed" value="{{ seed or "" }}"></div>
    </div>
    <div class="row">
      <div><label>Scenes</label><input type="text" name="scenes" value="{{ scenes or 10 }}"></div>
      <div><label>Seconds/scene</label><input type="text" name="sec" value="{{ sec or 8 }}"></div>
    </div>
    <div class="row">
      <div><label>Aspect ratio</label><input type="text" name="ar" value="{{ ar or '16:9' }}"></div>
      <div><label>FPS</label><input type="text" name="fps" value="{{ fps or 24 }}"></div>
    </div>
    <label><input type="checkbox" name="render" {{ 'checked' if render else '' }}> Render with Veo</label>
    <label style="margin-left:16px"><input type="checkbox" name="concat" {{ 'checked' if concat else '' }}> Concat to full_minute.mp4</label>
    <div style="margin-top:12px"><button type="submit">Generate</button></div>
  </form>
</div>

{% if markdown %}
<div class="card">
  <h3>Scene Prompts (Markdown)</h3>
  <pre>{{ markdown }}</pre>
</div>
{% endif %}

{% if clips %}
<div class="card">
  <h3>Clips</h3>
  <div class="grid">
    {% for c in clips %}
      <div class="thumb"><a href="{{ c['url'] }}" target="_blank">{{ c['name'] }}</a></div>
    {% endfor %}
  </div>
</div>
{% endif %}

{% if full %}
<div class="card">
  <h3>Full video</h3>
  <a href="{{ full }}" target="_blank">full_minute.mp4</a>
</div>
{% endif %}

</body></html>
""")

def to_markdown(master: str, style: str, scenes_out: List[Dict[str, Any]]) -> str:
    lines = [f"# Scenes\n\n**Master**: {master}\n\n**Style**: {style}\n\n---\n"]
    for s in scenes_out:
        lines.append(f"## {s.get('title','Scene')}\n**Scene {s.get('index')}**\n\n{s.get('prompt','')}\n\n---\n")
    return "\n".join(lines)

@app.get("/", response_class=HTMLResponse)
async def index():
    return INDEX_HTML.render(master="", style="", seed="", scenes=10, sec=8, ar="16:9", fps=24,
                             render=False, concat=False, markdown="", clips=[], full=None)

@app.post("/", response_class=HTMLResponse)
async def generate(
    master: str = Form(...),
    style: str = Form(""),
    seed: str = Form(""),
    scenes: int = Form(10),
    sec: int = Form(8),
    ar: str = Form("16:9"),
    fps: int = Form(24),
    render: Optional[str] = Form(None),
    concat: Optional[str] = Form(None),
):
    try:
        scenes_out = expand_scenes(master, style, int(scenes), int(sec))
    except Exception as e:
        return INDEX_HTML.render(master=master, style=style, seed=seed, scenes=scenes, sec=sec, ar=ar, fps=fps,
                                 render=bool(render), concat=bool(concat),
                                 markdown=f"Error expanding scenes: {e}", clips=[], full=None)

    # Save prompts + prepare run dir
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = OUT_ROOT / f"run-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scenes.json").write_text(json.dumps(scenes_out, indent=2), encoding="utf-8")
    md = to_markdown(master, style, scenes_out)
    (run_dir / "scenes.md").write_text(md, encoding="utf-8")

    clips = []
    full_url = None

    if render:
        # Render each scene via Veo
        veo = VeoClient(seconds=int(sec), ar=ar, fps=int(fps), seed=int(seed) if seed.strip() else None)
        clip_paths: List[Path] = []
        for s in scenes_out:
            idx = int(s.get("index", len(clip_paths) + 1))
            outp = run_dir / f"s{idx:02d}.mp4"
            try:
                veo.render(s.get("prompt", ""), outp)
                clip_paths.append(outp)
            except Exception as e:
                (run_dir / f"s{idx:02d}.err.txt").write_text(str(e), encoding="utf-8")

        clips = [{"name": p.name, "url": f"/runs/{run_dir.name}/{p.name}"} for p in clip_paths if p.exists()]

        if concat and clip_paths:
            try:
                out_full = run_dir / "full_minute.mp4"
                concat_ffmpeg(clip_paths, out_full)
                full_url = f"/runs/{run_dir.name}/{out_full.name}"
            except Exception as e:
                (run_dir / "concat.err.txt").write_text(str(e), encoding="utf-8")

    return INDEX_HTML.render(
        master=master, style=style, seed=seed, scenes=scenes, sec=sec, ar=ar, fps=fps,
        render=bool(render), concat=bool(concat), markdown=md, clips=clips, full=full_url
    )
