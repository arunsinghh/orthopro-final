# Run this project on YOUR computer (VS Code) — step by step

The most common "errors" are simply: Python packages not installed, or the
PostgreSQL database not created yet. Follow this once and it will always work.

## 1. Install (one time)
1. **Python 3.11+** — python.org → check "Add python to PATH" during install.
2. **PostgreSQL 16** — download from postgresql.org (the EDB installer).
   During install remember the **postgres password** you choose.
3. **VS Code** — open the downloaded project folder in it.

## 2. Create the database (one time)
Open **SQL Shell (psql)** from the Start menu, connect with your postgres
password, then paste:

```sql
CREATE ROLE orthopro_app LOGIN PASSWORD 'orthopro_app';
CREATE DATABASE orthopro OWNER orthopro_app;
CREATE DATABASE orthopro_test OWNER orthopro_app;
\q
```

Then open the project's `.env` file in VS Code and make sure this line matches
what you typed above (password after the `:`):

```
DATABASE_URL=postgresql://orthopro_app:orthopro_app@127.0.0.1:5432/orthopro
```

## 3. Install packages & build the data (one time)
In VS Code: **Terminal → New Terminal**, then:

```bash
pip install -r requirements.txt
python scripts/init_db.py          # creates all tables
python scripts/seed_dev.py --demo  # services, products+photos, sample data
python scripts/create_admin.py     # choose your admin username/password
```

## 4. Run
```bash
python run.py
```
Open **http://localhost:5000** (website) and **http://localhost:5000/admin** (CRM).

## If you see an error…
| Error you see | What it means | Fix |
|---|---|---|
| `No module named 'flask'` | packages missing | `pip install -r requirements.txt` |
| `Connection refused ... 5432` | PostgreSQL not running | Start it: Windows *Services* → start **postgresql-x64-16** |
| `password authentication failed` | role/password mismatch | redo step 2, or edit `.env` password to match |
| `database "orthopro" does not exist` | DB not created | redo step 2 |
| `port 5000 already in use` | another app on 5000 | close it, or run `set PORT=5001 && python run.py` |
| `Permission denied (pg)` | wrong postgres password in .env | fix `.env` |

Notes
- Product photos are real images inside `app/static/img/…` — the old emoji
  placeholders have been fully removed; even a database without photo links
  shows the real photos (the app maps each product name to its photo).
- Your data lives in PostgreSQL only. There is no SQLite anywhere.
- Self-check: `python -m pytest tests/ -q` should end with "passed".

## Updating an older copy of this project
If you downloaded the project earlier and pull a newer version later, run these
again in the Terminal (they are safe and never delete your data):

```bash
pip install -r requirements.txt
python scripts/init_db.py          # adds any new tables/columns
python scripts/seed_dev.py         # refreshes reference content + photos
python run.py
```

The **Gallery page now fills itself automatically** when the site starts —
no extra command needed. If the gallery or any page ever shows an error after
an update, re-run `python scripts/init_db.py` and restart `python run.py`.
