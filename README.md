# PocketSmart AI

PocketSmart AI is a FastAPI + Jinja2 budget-planning web app with Gemini-powered recommendations for home interiors, parties, and jewelry.

## 1. Create a virtual environment (Windows)

```powershell
python -m venv venv
venv\Scripts\activate
```

## 2. Install dependencies

```powershell
pip install -r requirements.txt
```

## 3. Configure Gemini

Copy `.env.example` to `.env` and set the Gemini API key and model:

```env
GEMINI_API_KEY=your_google_gemini_api_key_here
SECRET_KEY=replace_with_a_long_random_secret
GEMINI_MODEL=gemini-3.8-flash
```

Never commit `.env` or share your API key.

## 4. Run

```powershell
python -m uvicorn app:app --reload
```

Open http://127.0.0.1:8000

## Main routes

- `/` — landing page
- `/register` — registration
- `/login` — login
- `/dashboard` — planner dashboard
- `/home-planner` — home planner
- `/party-planner` — party planner
- `/jewelry-planner` — jewelry planner
- `/history` — recommendation history

## Important

The application currently stores users and history in memory. Restarting the server clears accounts and history. Use SQLite/PostgreSQL for production.

## Troubleshooting

- If `uvicorn` is not found, activate the virtual environment first: `venv\Scripts\activate`.
- If a planner shows a Gemini API error, check `GEMINI_API_KEY` in `.env` and make sure the selected `GEMINI_MODEL` is available to your API key.
- Accounts and recommendation history are stored in memory and reset when the server restarts.
