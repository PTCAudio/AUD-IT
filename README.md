# AUD-IT Suite

**Phoenix Theatre Company — Audio Department**

Equipment inventory and task management web application.

## Modules
- **Inventory** — Track gear across Stephenson, Hormel, and Hardes spaces
- **Tasks & Journal** — Task management with show/space organization and daily hour logging

## Quick Start (Local)

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/audit-suite.git
cd audit-suite

# Create .env file
cp .env.example .env
# Edit .env and set APP_PASSWORD and SECRET_KEY

# Install dependencies
pip install -r requirements.txt

# Run
python app.py
# Open http://localhost:5000
```

## Deploy to Render.com

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) and sign in with GitHub
3. Click **New → Web Service**
4. Select this repository
5. Settings will auto-populate from `render.yaml`
6. Add environment variable: `APP_PASSWORD` = your chosen password
7. Click **Deploy**

Your app will be live at `https://audit-suite.onrender.com`

## Restoring Data

After deploying, you can import your existing data:

1. Open the app in your browser
2. Log in with your password
3. Click **Import** in the header
4. Select your existing inventory JSON backup
5. Your data populates the database

The app accepts legacy inventory backups (from the standalone HTML version)
as well as full suite backups.

## Tech Stack
- Flask + SQLite
- Vanilla JS frontend
- Gunicorn for production
