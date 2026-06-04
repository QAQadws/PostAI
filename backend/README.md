# PostAI Backend

FastAPI backend for the intelligent poster design multi-agent pipeline.

## Run

Recommended: use a dedicated virtual environment so Pydantic v2 does not affect
other Python projects.

Windows PowerShell:

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Linux/macOS:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## APIs

- `POST /api/v1/generate`
- `POST /api/v1/generate/stream`
- `GET /assets/{filename}`
- `GET /health`

Example:




```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/generate `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"prompt":"制作一张科技风 AI 会议海报","width":768,"height":1152,"max_iterations":2}'
```

Generated poster PNG files are saved under `generated/` and exposed through
`/assets/...`. The API still includes `final_image` base64 for direct preview.

## Configuration

Configuration is loaded from `backend/.env`. Start from the template:

```powershell
Copy-Item .env.example .env
```

Linux/macOS:

```bash
cp .env.example .env
```

The backend uses local rule agents by default. Fill these values in `.env` to
enable OpenAI-compatible structured LLM calls for Content, Style, and Layout:

```text
ALLOW_MODEL_FALLBACK=true
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
LLM_RESPONSE_FORMAT=json_schema
```

For providers that do not support JSON Schema response format, set
`LLM_RESPONSE_FORMAT=json_object`. In this mode the backend injects the target
JSON Schema into the prompt and normalizes common layout-like content payloads
from weaker models into `ContentPlan` when possible.

If the LLM call or schema validation fails, the backend records a warning and
falls back to the deterministic local agent so generation can continue.
Set `ALLOW_MODEL_FALLBACK=false` to disable this behavior; configured model
failures will stop generation and return an error event/response instead.

Vision critique is configured separately because text-only models cannot read
rendered poster images:

```text
VISION_API_KEY=your-vision-api-key
VISION_BASE_URL=https://api.openai.com/v1
VISION_MODEL=gpt-4.1-mini
```

If the vision model is unavailable, the backend falls back to the heuristic
critic and records the fallback in `warnings`.

Generated illustrations are configured separately. When these values are blank,
the new IllustrationAgent is skipped and the original poster generation flow
continues:

```text
IMAGE_API_KEY=your-image-api-key
IMAGE_BASE_URL=https://api.openai.com/v1
IMAGE_MODEL=gpt-image-1
IMAGE_SIZE=1024x1024
IMAGE_TIMEOUT_SECONDS=120
```

Requests can disable this per job with `enable_generated_illustrations=false`,
or cap cost with `max_generated_illustrations` from `0` to `5`.

## Linux Notes

The renderer searches common Windows, Linux, and macOS font paths. For better
Chinese text rendering on Linux, install a CJK font package such as Noto CJK:

```bash
sudo apt-get install fonts-noto-cjk
```
