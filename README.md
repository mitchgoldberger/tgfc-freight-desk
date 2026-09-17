# TGFC Freight Desk

Sales requests a freight rate → the freight desk sends the RFQ to carriers → freight logs the bids and posts the price back on the request. Streamlit app with a Supabase (Postgres) database and its own email/password login.

## Roles

| Role | Can |
|---|---|
| sales | submit requests, see the queue and prices, mark a quote booked |
| freight | everything sales can, plus send RFQs, log bids, price, manage the carrier list |
| admin | everything freight can, plus add/reset/deactivate users |

## Files

- `app.py` — the app
- `db.py` — database layer (Postgres via `DATABASE_URL`; falls back to a local SQLite file when it's not set, for testing)
- `requirements.txt`
- `.streamlit/config.toml` — TGFC navy/gray/white theme
- `.streamlit/secrets.toml.example` — the secrets the app needs (never commit real values)

## Deploy (Streamlit Community Cloud + Supabase) — about 15 minutes, no terminal needed

**1. Database (Supabase)**
1. supabase.com → New project (name it `tgfc-freight-desk`, pick a region near you, save the database password).
2. Project → **Connect** (top bar) → Method **URI** → choose the **Session pooler** connection string (Streamlit Cloud needs the pooler, not the direct connection). It looks like
   `postgresql://postgres.abcd1234:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres`
   Replace `[YOUR-PASSWORD]` with the real password. That is your `DATABASE_URL`.
   The app creates its own tables the first time it runs — nothing to set up in Supabase.

**2. Code (GitHub)**
1. github.com → New repository → `tgfc-freight-desk`, Private → Create.
2. **Add file → Upload files** → drag in `app.py`, `db.py`, `requirements.txt`, `README.md`, `.gitignore` → Commit.
3. **Add file → Create new file** → in the name box type `.streamlit/config.toml` (the slash creates the folder) → paste the contents of that file → Commit.

**3. App (Streamlit Community Cloud)**
1. share.streamlit.io → **Create app** → Deploy a public app from GitHub → repo `tgfc-freight-desk`, branch `main`, main file `app.py`. Pick an app URL (e.g. `tgfc-freight-desk`).
2. **Advanced settings → Secrets** → paste:
   ```toml
   DATABASE_URL = "postgresql://...the pooler string from step 1..."
   ADMIN_EMAIL = "mitch@thetgfc.com"
   ADMIN_PASSWORD = "a-strong-first-password"
   ADMIN_NAME = "Mitch Goldberger"
   ```
3. **Deploy**. First build takes ~2 minutes.

Keep the app **public** on Streamlit's side: the app has its own login, and a "private" Streamlit app would force every viewer to also sign into Streamlit with an allow-listed Google/GitHub email.

**4. First sign-in**
1. Open the app URL, sign in as the admin, set your own password.
2. **Users** → add Gary (`garygoldberger50@gmail.com`, sales), Taylor (`taylor@thetgfc.com`, sales), Max (`max@thetgfc.com`, freight). Give each a temporary password; they'll be asked to choose their own the first time they sign in.
3. **Carriers** → add the carriers/brokers the freight desk sends RFQs to.
4. Send everyone the app URL.

## How the RFQ goes out

No mail server is involved. When freight picks the carriers, the app writes the RFQ (subject + body with every load detail) and shows one **✉ Carrier** button per carrier — each opens a pre-filled email in Outlook/Mail from freight's own address — plus the plain text to copy. "Mark RFQ sent" records who was asked and moves the request to *RFQ out*. When the price is posted, an **✉ Email rep** button does the same for the rep.

## Running locally

```
pip install -r requirements.txt
streamlit run app.py
```
Without `DATABASE_URL` it uses `freight_desk.sqlite3` in the folder. Put `ADMIN_EMAIL` / `ADMIN_PASSWORD` / `ADMIN_NAME` in `.streamlit/secrets.toml` to create the first admin.
