# Hotel Grand Garden HMS

**Domain:** https://hms.hotelgrand.com.np  
**Public site:** https://hotelgrand.com.np (separate repo)  
**Database:** shared Aiven PostgreSQL  
**Images:** Cloudinary (fallback: local `/static/uploads`)  

## QR flow
1. HMS generates QR → encodes `https://hotelgrand.com.np/qr/<token>`
2. Guest scans → public QR menu
3. Order saved to shared `orders` table
4. HMS Kitchen / Orders / POS see the order

## Vercel env
```
DATABASE_URL=...aiven...
SECRET_KEY=...
PUBLIC_SITE_URL=https://hotelgrand.com.np
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
```

## Local (no DB config)
```bash
pip install -r requirements.txt
python run.py
# uses SQLite automatically if DATABASE_URL unset
# login: admin / admin123
```

# Hotel Grand Garden HMS

Production-oriented Hotel Management System for **HOTEL GRAND GARDEN** (Urlabari-5, Morang).

## Stack

- Python 3.10+ · Flask · SQLAlchemy · Jinja2 · Vanilla JS
- **Local:** SQLite (zero config — no database setup required)
- **Production / Vercel:** PostgreSQL via `DATABASE_URL` (Aiven, Neon, etc.)

## Quick start (local)

```bash
cd hotel-grand-garden-hms
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:5000

**Default login:** `admin` / `admin123` — change immediately.

SQLite file is created automatically at `instance/hotel_hms.db`.

## Vercel + Aiven (PostgreSQL)

1. Create a PostgreSQL database on [Aiven](https://aiven.io) (or Neon).
2. Copy the connection string (e.g. `postgres://user:pass@host:port/db?sslmode=require`).
3. Deploy to Vercel:

```bash
# Install Vercel CLI if needed
npm i -g vercel
vercel
```

4. In Vercel project **Settings → Environment Variables** set:

| Name | Value |
|------|--------|
| `DATABASE_URL` | your Aiven/Neon postgres URL |
| `SECRET_KEY` | long random string |
| `FLASK_ENV` | `production` |

5. Redeploy. Tables are created on first request via `db.create_all()` + seed.

`vercel.json` routes all traffic to `wsgi.py`.

## Core modules

| Module | Path |
|--------|------|
| Login / roles / permissions | `/login` |
| Dashboard | `/dashboard` |
| Rooms & Tables + QR | `/rooms`, `/rooms/tables`, `/rooms/qr` |
| Bookings | `/bookings` |
| Menu & categories | `/menu` |
| Public QR order (no login) | `/order/<secure-token>` |
| Orders admin | `/orders` |
| Kitchen / KOT | `/kitchen` |
| POS | `/pos` |
| Billing (VAT inclusive 13%) | `/billing` |
| Staff + permissions + sessions | `/staff` |
| Attendance | `/staff/attendance` |
| Payroll (running / final) | `/payroll` |
| Business / Tax / OT settings | `/settings` |

## VAT (inclusive)

Prices are VAT-inclusive. Example Rs. 500:

- Before VAT = 500 / 1.13 ≈ **442.48**
- VAT 13% = **57.52**
- Total remains **500.00**

PAN must be set under **Settings → Business** before creating bills.

## Security

- Password hashing (Werkzeug)
- Flask-Login sessions
- CSRF (Flask-WTF)
- Role + granular permission checks on routes
- Secure non-sequential QR tokens
- Server-side price & total calculation
- No secrets hardcoded for production

## Notes

- Full HR features (leave approval UI, fine auto-calc, email) are modeled in the database and partially wired; extend from existing services.
- Email notifications require `MAIL_*` env vars.
- For production, set a strong `SECRET_KEY` and never commit `.env`.
