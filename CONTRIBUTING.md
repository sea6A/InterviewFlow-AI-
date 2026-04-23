# Contributing

Thanks for contributing to InterviewFlow-AI.

## Development Setup

1. Copy `.env.example` to `.env`
2. Fill in `DASHSCOPE_API_KEY`
3. Install backend dependencies:

```bash
cd apps/server
pip install -r requirements.txt
```

4. Start the backend:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 3001
```

5. Open the web entry page:

- `apps/web/index.html`
- or `apps/web/demo-client.html`

## Contribution Guidelines

- Keep changes focused and minimal.
- Prefer updating docs when behavior changes.
- Do not commit secrets, local `.env`, or generated cache files.
- Keep API field names and event names aligned across frontend, backend, and `packages/shared`.

## Pull Requests

Please include:

- What changed
- Why it changed
- How it was tested
- Screenshots or event samples for UI / realtime behavior when helpful
