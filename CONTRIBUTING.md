# Contributing

Thank you for contributing to Vigilath.

## Development workflow

1. Fork the repository and create a focused branch.
2. Copy `backend/.env.example` to a local `.env` and provide a unique
   `SECRET_KEY`. Never commit that file.
3. Install dependencies for the component you are changing.
4. Add or update tests and documentation.
5. Run the relevant checks locally before opening a pull request.

Backend:

```bash
python -m pip install -r backend/requirements.txt
SECRET_KEY="$(openssl rand -hex 32)" python -m compileall -q backend
pytest -q
```

Frontend:

```bash
cd frontend
npm ci
npm run lint
npm run build
```

Keep pull requests scoped and describe how they were tested. Do not include
generated bundles, runtime databases, recordings, customer material, secrets,
or browser sessions. Contributions are submitted under the MIT License.
