"""TGFC Freight Desk — sales requests a rate, freight sends the RFQ, price comes back on the request."""
from __future__ import annotations

import random
import string
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import bcrypt
import streamlit as st

import db

st.set_page_config(page_title="TGFC Freight Desk", page_icon="🚚", layout="wide")

# ----------------------------------------------------------------------------- styling
NAVY = "#12294A"
NAVY2 = "#1F4E8C"
STATUS = {
    "open": ("New", "#B7791F", "#FBF1DC"),
    "rfq_sent": ("RFQ out", "#7C3AED", "#EDE6FB"),
    "quoted": ("Priced", "#1F7A4D", "#DFF3E7"),
    "booked": ("Booked", "#1F4E8C", "#DEE8F7"),
    "declined": ("Can't cover", "#6B7280", "#E9EBEF"),
}
st.markdown(
    f"""
<style>
.block-container {{ padding-top: 1.2rem; max-width: 1150px; }}
.fd-top {{ background:{NAVY}; color:#fff; border-radius:10px; padding:12px 18px; display:flex; align-items:center; gap:14px; margin-bottom:14px; }}
.fd-top .mark {{ background:#fff; color:{NAVY}; font-weight:800; font-size:11px; border-radius:7px; padding:8px 7px; letter-spacing:.02em; }}
.fd-top h1 {{ font-size:18px; margin:0; color:#fff; font-weight:600; }}
.fd-top small {{ display:block; font-size:12px; opacity:.75; }}
.fd-top .who {{ margin-left:auto; font-size:12px; opacity:.85; }}
.badge {{ display:inline-block; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; padding:3px 9px; border-radius:999px; }}
.ref {{ font-family: ui-monospace, Menlo, monospace; font-size:12px; color:#5B6779; letter-spacing:.04em; }}
.lane {{ font-size:19px; font-weight:700; margin:4px 0 2px; }}
.lane .to {{ color:#8A94A6; font-weight:400; margin:0 8px; }}
.chip {{ display:inline-block; background:#fff; border:1px solid #D3DAE4; border-radius:6px; padding:2px 9px; font-size:13px; margin:2px 4px 2px 0; }}
.chip b {{ font-weight:700; }}
.meta {{ font-size:13px; color:#5B6779; }}
.meta b {{ color:#1B2433; }}
.small {{ font-size:12px; color:#8A94A6; }}
.price {{ font-size:26px; font-weight:800; color:#1F7A4D; line-height:1.1; }}
.kv {{ font-size:12px; color:#5B6779; }} .kv b {{ display:block; color:#1B2433; font-size:15px; }}
.stat {{ background:#F3F5F8; border:1px solid #D3DAE4; border-radius:10px; padding:10px 14px; }}
.stat .l {{ font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:#5B6779; font-weight:600; }}
.stat .v {{ font-size:26px; font-weight:700; line-height:1.15; }}
.stat .s {{ font-size:12px; color:#8A94A6; }}
div[data-testid="stExpander"] details {{ border-radius:10px; }}
</style>
""",
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------- helpers
def money(v) -> str:
    try:
        return "${:,.0f}".format(float(v))
    except Exception:
        return "—"


def fmt_n(v) -> str:
    try:
        return "{:,.0f}".format(float(v))
    except Exception:
        return ""


def fmt_d(v) -> str:
    if not v:
        return ""
    if isinstance(v, str):
        try:
            v = date.fromisoformat(v[:10])
        except Exception:
            return v
    return v.strftime("%b %-d, %Y")


def to_dt(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def ago(v) -> str:
    d = to_dt(v)
    if not d:
        return ""
    s = (datetime.now(timezone.utc) - d).total_seconds()
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)}m ago"
    if s < 86400:
        return f"{int(s // 3600)}h ago"
    return f"{int(s // 86400)}d ago"


def badge(status: str) -> str:
    label, fg, bg = STATUS.get(status, (status, "#555", "#eee"))
    return f'<span class="badge" style="color:{fg};background:{bg}">{label}</span>'


def esc(s) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def new_ref() -> str:
    d = datetime.now().strftime("%y%m%d")
    tail = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"FR-{d}-{tail}"


def user_name(uid) -> str:
    if not uid:
        return "—"
    u = db.fetchone("SELECT name FROM users WHERE id=%s", (uid,))
    return u["name"] if u else "—"


def mailto(to: str, subject: str, body: str) -> str:
    return "mailto:" + urllib.parse.quote(to) + "?" + urllib.parse.urlencode(
        {"subject": subject, "body": body}, quote_via=urllib.parse.quote
    )


# ----------------------------------------------------------------------------- auth
def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_pw(pw: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), h.encode())
    except Exception:
        return False


def bootstrap_admin():
    """If there are no users yet, create the admin from secrets (ADMIN_EMAIL / ADMIN_PASSWORD / ADMIN_NAME)."""
    if db.fetchone("SELECT id FROM users LIMIT 1"):
        return
    try:
        email = st.secrets.get("ADMIN_EMAIL")
        pw = st.secrets.get("ADMIN_PASSWORD")
        name = st.secrets.get("ADMIN_NAME", "Admin")
    except Exception:
        email = pw = None
    if email and pw:
        db.run(
            "INSERT INTO users (email, name, role, password_hash, must_change) VALUES (%s,%s,%s,%s,%s)",
            (email.lower().strip(), name, "admin", hash_pw(pw), True),
        )


def current_user():
    u = st.session_state.get("user")
    if not u:
        return None
    fresh = db.fetchone("SELECT id,email,name,role,must_change,active FROM users WHERE id=%s", (u["id"],))
    if not fresh or not db.as_bool(fresh["active"]):
        st.session_state.pop("user", None)
        return None
    st.session_state["user"] = fresh
    return fresh


def login_screen():
    st.markdown(
        f'<div class="fd-top"><span class="mark">TGFC</span><div><h1>Freight Desk</h1><small>Sales request → carrier RFQ → price back</small></div></div>',
        unsafe_allow_html=True,
    )
    if not db.fetchone("SELECT id FROM users LIMIT 1"):
        st.warning(
            "No users exist yet. Add ADMIN_EMAIL, ADMIN_PASSWORD and ADMIN_NAME to the app's secrets and reload — "
            "that creates the first admin account, who then adds everyone else under Users."
        )
        return
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        with st.form("login"):
            st.subheader("Sign in")
            email = st.text_input("Email")
            pw = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                u = db.fetchone("SELECT * FROM users WHERE email=%s", (email.lower().strip(),))
                if u and db.as_bool(u["active"]) and check_pw(pw, u["password_hash"]):
                    st.session_state["user"] = u
                    st.rerun()
                else:
                    st.error("That email and password don't match.")


def change_password_screen(u, forced=False):
    if forced:
        st.info("Welcome — please set your own password before continuing.")
    with st.form("chpw"):
        st.subheader("Set a new password")
        p1 = st.text_input("New password", type="password")
        p2 = st.text_input("Repeat it", type="password")
        if st.form_submit_button("Save password", type="primary"):
            if len(p1) < 8:
                st.error("Use at least 8 characters.")
            elif p1 != p2:
                st.error("The two entries don't match.")
            else:
                db.run("UPDATE users SET password_hash=%s, must_change=%s WHERE id=%s", (hash_pw(p1), False, u["id"]))
                st.success("Password saved.")
                st.rerun()


# ----------------------------------------------------------------------------- pages
def freight_desk_emails() -> list[str]:
    rows = db.fetchall("SELECT email FROM users WHERE active=%s AND role IN ('freight','admin') ORDER BY role, email", (True,))
    return [r["email"] for r in rows]


def notify_text(r) -> tuple[str, str]:
    subject = f"Freight rate request {r['ref']}: {r['origin']} → {r['dest']} · {fmt_n(r['pallets'])} plt / {fmt_n(r['lbs'])} lb {r['temp']}"
    lines = [
        f"New freight rate request in the Freight Desk app — {r['ref']}", "",
        f"Pick up:      {r['origin']}",
        f"Deliver to:   {r['dest']}",
        f"Load:         {fmt_n(r['pallets'])} plt / {fmt_n(r['lbs'])} lb, {str(r['temp']).capitalize()}, {r['truck']}",
        f"Pick-up date: {fmt_d(r['ship_date'])}" + (f"   Deliver by: {fmt_d(r['deliver_by'])}" if r.get('deliver_by') else ""),
    ]
    if r.get("product"):
        lines.append(f"Product:      {r['product']}")
    if r.get("customer"):
        lines.append(f"Customer:     {r['customer']}")
    if r.get("po"):
        lines.append(f"PO:           {r['po']}")
    if r.get("notes"):
        lines.append(f"Notes:        {r['notes']}")
    lines += ["", "Open the queue: https://tgfc-freight-desk.streamlit.app"]
    return subject, "\n".join(lines)


def notify_button(r, label="✉ Notify freight desk", key=None):
    """A mailto button to the freight desk (freight + admin users) pre-filled with the request."""
    to = freight_desk_emails()
    if not to:
        return
    subject, body = notify_text(r)
    st.link_button(label, mailto(",".join(to), subject, body), help="Opens a pre-written email to " + ", ".join(to))


def header(u):
    role = {"sales": "Sales", "freight": "Freight desk", "admin": "Admin"}[u["role"]]
    st.markdown(
        f'<div class="fd-top"><span class="mark">TGFC</span><div><h1>Freight Desk</h1><small>Sales request → carrier RFQ → price back</small></div>'
        f'<span class="who">{esc(u["name"])} · {role}</span></div>',
        unsafe_allow_html=True,
    )


def page_new_request(u):
    st.subheader("Request a freight rate")
    st.caption("Fill this in and the freight desk sees it in the queue immediately. They send the RFQ to carriers and post the price back on this request.")
    just = st.session_state.get("just_submitted")
    if just:
        r = db.fetchone("SELECT * FROM requests WHERE ref=%s", (just,))
        if r:
            with st.container(border=True):
                st.success(f"Sent — reference **{just}**. It's in the freight desk's queue now.")
                c1, c2, _ = st.columns([1.6, 1, 3])
                with c1:
                    notify_button(r, key="notify_new")
                if c2.button("Done", key="dismiss_new"):
                    st.session_state.pop("just_submitted", None)
                    st.rerun()
                st.caption("Optional: the button opens a ready-made email to the freight desk so they see it right away.")
    with st.form("new_request", clear_on_submit=True):
        c1, c2 = st.columns(2)
        origin = c1.text_input("Pick-up location", placeholder="Shipper — City, ST")
        dest = c2.text_input("Destination", placeholder="Consignee — City, ST")
        c1, c2, c3, c4 = st.columns(4)
        pallets = c1.number_input("Pallets", min_value=0, max_value=60, step=1, value=0)
        lbs = c2.number_input("Pounds", min_value=0, step=500, value=0)
        ship = c3.date_input("Est. pick-up date", value=date.today() + timedelta(days=3), min_value=date.today())
        deliver = c4.date_input("Deliver by (optional)", value=None, min_value=date.today())
        c1, c2 = st.columns(2)
        temp = c1.radio("Temperature", ["Frozen", "Refrigerated", "Dry"], horizontal=True)
        truck = c2.radio("Truck", ["Full truckload", "LTL / partial"], horizontal=True)
        c1, c2, c3 = st.columns(3)
        product = c1.text_input("Product", placeholder="e.g. Chicken leg quarters, 40 lb cs")
        customer = c2.text_input("Customer", placeholder="Account name")
        po = c3.text_input("PO / reference")
        notes = st.text_area("Notes for freight (optional)", placeholder="Appointment required, liftgate, pallet exchange, multi-stop, blind ship…", height=80)
        if st.form_submit_button("Send to freight desk", type="primary"):
            missing = []
            if not origin.strip():
                missing.append("pick-up location")
            if not dest.strip():
                missing.append("destination")
            if pallets <= 0:
                missing.append("pallets")
            if lbs <= 0:
                missing.append("pounds")
            if deliver and deliver < ship:
                st.error("Deliver-by date is before the pick-up date.")
                return
            if missing:
                st.error("Still needed: " + ", ".join(missing) + ".")
                return
            ref = new_ref()
            db.run(
                """INSERT INTO requests (ref,status,requester_id,origin,dest,pallets,lbs,ship_date,deliver_by,temp,truck,product,customer,po,notes)
                   VALUES (%s,'open',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (ref, u["id"], origin.strip(), dest.strip(), int(pallets), int(lbs), ship, deliver, temp.lower(),
                 "FTL" if truck.startswith("Full") else "LTL", product.strip(), customer.strip(), po.strip(), notes.strip()),
            )
            st.session_state["just_submitted"] = ref
            st.rerun()


def rfq_text(r, reply_by: str, msg: str, sender: str) -> tuple[str, str]:
    subject = f"RFQ {r['ref']}: {r['origin']} → {r['dest']} · {fmt_n(r['pallets'])} plt / {fmt_n(r['lbs'])} lb {r['temp']} · pick up {fmt_d(r['ship_date'])}"
    lines = [
        "Hello,",
        "",
        "Third Generation Food Company (TGFC) is requesting an all-in rate for the following load:",
        "",
        f"Reference:        {r['ref']}",
        f"Pick up:          {r['origin']}",
        f"Deliver to:       {r['dest']}",
        f"Pallets:          {fmt_n(r['pallets'])}",
        f"Weight:           {fmt_n(r['lbs'])} lb",
        f"Temperature:      {str(r['temp']).capitalize()}",
        f"Equipment:        {'Full truckload' if r['truck'] == 'FTL' else 'LTL / partial'}",
        f"Est. pick-up:     {fmt_d(r['ship_date'])}",
    ]
    if r.get("deliver_by"):
        lines.append(f"Deliver by:       {fmt_d(r['deliver_by'])}")
    if r.get("product"):
        lines.append(f"Commodity:        {r['product']}")
    if r.get("notes"):
        lines.append(f"Notes:            {r['notes']}")
    lines.append("")
    if msg:
        lines += [msg, ""]
    lines.append("Please reply with your all-in rate including fuel, transit time, and any accessorials" + (f" by {reply_by}" if reply_by else "") + ".")
    lines += ["", "Thank you,", sender, "Third Generation Food Company"]
    return subject, "\n".join(lines)


def price_text(r) -> tuple[str, str]:
    subject = f"Freight rate ready — {r['ref']}: {r['origin']} → {r['dest']} · {money(r['sell_rate'])}"
    per_lb = f"${float(r['sell_rate']) / float(r['lbs']):.3f}" if r.get("sell_rate") and r.get("lbs") else ""
    lines = [
        "Your freight rate is ready.", "",
        f"Reference:   {r['ref']}",
        f"Lane:        {r['origin']} → {r['dest']}",
        f"Load:        {fmt_n(r['pallets'])} plt / {fmt_n(r['lbs'])} lb, {str(r['temp']).capitalize()}, {r['truck']}",
        f"Pick up:     {fmt_d(r['ship_date'])}",
        f"Rate:        {money(r['sell_rate'])} all-in" + (f"  ({per_lb} / lb)" if per_lb else ""),
    ]
    if r.get("sell_carrier"):
        lines.append(f"Carrier:     {r['sell_carrier']}")
    if r.get("sell_transit"):
        lines.append(f"Transit:     {r['sell_transit']}")
    if r.get("sell_notes"):
        lines.append(f"Notes:       {r['sell_notes']}")
    lines += ["", "— TGFC Freight Desk"]
    return subject, "\n".join(lines)


def request_header(r):
    st.markdown(
        f'<span class="ref">{esc(r["ref"])}</span>&nbsp; {badge(r["status"])} '
        f'<span class="small" style="float:right">{ago(r["created_at"])}</span>'
        f'<div class="lane">{esc(r["origin"])}<span class="to">→</span>{esc(r["dest"])}</div>'
        f'<span class="chip"><b>{fmt_n(r["pallets"])}</b> pallets</span><span class="chip"><b>{fmt_n(r["lbs"])}</b> lb</span>'
        f'<span class="chip">Pick up <b>{fmt_d(r["ship_date"])}</b></span>'
        + (f'<span class="chip">Deliver by <b>{fmt_d(r["deliver_by"])}</b></span>' if r.get("deliver_by") else "")
        + f'<span class="chip">{esc(str(r["temp"]).capitalize())}</span><span class="chip">{esc(r["truck"])}</span>',
        unsafe_allow_html=True,
    )
    meta = []
    if r.get("product"):
        meta.append(f"Product <b>{esc(r['product'])}</b>")
    if r.get("customer"):
        meta.append(f"Customer <b>{esc(r['customer'])}</b>")
    if r.get("po"):
        meta.append(f"PO <b>{esc(r['po'])}</b>")
    if meta:
        st.markdown('<div class="meta">' + " &nbsp;·&nbsp; ".join(meta) + "</div>", unsafe_allow_html=True)
    if r.get("notes"):
        st.markdown(esc(r["notes"]))
    st.markdown(f'<div class="small">Requested by {esc(user_name(r["requester_id"]))}</div>', unsafe_allow_html=True)


def step_rfq(r, u):
    """Step 1 — freight picks carriers and gets a ready-to-send RFQ."""
    carriers = db.fetchall("SELECT * FROM carriers WHERE active=%s ORDER BY name", (True,))
    with st.expander("1 · Send RFQ to carriers", expanded=True):
        names = [c["name"] for c in carriers]
        chosen = st.multiselect("Carriers to ask", names, key=f"rfqc{r['id']}")
        extra = st.text_input("Other addresses (comma-separated)", key=f"rfqe{r['id']}", placeholder="dispatch@carrier.com, quotes@broker.com")
        c1, c2 = st.columns([1, 2])
        reply_by = c1.text_input("Quotes needed by", key=f"rfqr{r['id']}", value=(date.today() + timedelta(days=1)).strftime("%b %-d") + " noon")
        msg = c2.text_input("Message to carriers (optional)", key=f"rfqm{r['id']}", placeholder="Reefer set to -10°F, live load, drop trailer…")
        picked = [(c["name"], c["email"]) for c in carriers if c["name"] in chosen]
        for e in [x.strip() for x in extra.replace(";", ",").split(",") if x.strip()]:
            picked.append((e, e))
        subject, body = rfq_text(r, reply_by, msg, u["name"])
        if picked:
            st.markdown("**Ready to send — open each in Outlook, or copy the text.**")
            cols = st.columns(min(4, len(picked)))
            for i, (n, e) in enumerate(picked):
                cols[i % len(cols)].link_button(f"✉ {n}", mailto(e, subject, body), use_container_width=True)
            st.text_area("RFQ text", value=f"Subject: {subject}\n\n{body}", height=260, key=f"rfqt{r['id']}")
        b1, b2, _ = st.columns([1.3, 1, 3])
        if b1.button("Mark RFQ sent", key=f"rfqs{r['id']}", type="primary", disabled=not picked):
            for n, e in picked:
                db.run("INSERT INTO rfq_carriers (request_id, carrier_name, carrier_email) VALUES (%s,%s,%s)", (r["id"], n, e))
                db.run("INSERT INTO bids (request_id, carrier_name) VALUES (%s,%s)", (r["id"], n))
            db.run(
                "UPDATE requests SET status='rfq_sent', rfq_sent_at=%s, rfq_sent_by=%s, rfq_reply_by=%s, rfq_message=%s WHERE id=%s",
                (db.now(), u["id"], reply_by, msg, r["id"]),
            )
            st.rerun()
        if b2.button("Can't cover", key=f"dec{r['id']}"):
            st.session_state[f"declining{r['id']}"] = True
        if st.session_state.get(f"declining{r['id']}"):
            note = st.text_input("Reason for sales", key=f"decn{r['id']}")
            if st.button("Send back to sales", key=f"decb{r['id']}"):
                db.run("UPDATE requests SET status='declined', decline_note=%s, quoted_at=%s, quoted_by=%s WHERE id=%s", (note, db.now(), u["id"], r["id"]))
                st.session_state.pop(f"declining{r['id']}", None)
                st.rerun()


def rfq_summary(r):
    sent = db.fetchall("SELECT carrier_name FROM rfq_carriers WHERE request_id=%s ORDER BY id", (r["id"],))
    names = ", ".join(c["carrier_name"] for c in sent) or "—"
    st.markdown(
        f'<div class="small">RFQ sent to <b>{esc(names)}</b> by {esc(user_name(r["rfq_sent_by"]))} · {ago(r["rfq_sent_at"])}'
        + (f' · quotes due {esc(r["rfq_reply_by"])}' if r.get("rfq_reply_by") else "") + "</div>",
        unsafe_allow_html=True,
    )


def step_bids_and_price(r, u):
    """Steps 2 and 3 — log carrier bids, pick the winner, price it back to sales."""
    bids = db.fetchall("SELECT * FROM bids WHERE request_id=%s ORDER BY id", (r["id"],))
    with st.expander("2 · Carrier bids", expanded=True):
        st.markdown('<div class="small">Type each carrier\'s reply as it comes in, then save.</div>', unsafe_allow_html=True)
        h = st.columns([2.2, 1.2, 1.2, 3])
        for col, lab in zip(h, ("Carrier", "Rate (all-in $)", "Transit", "Notes")):
            col.markdown(f"<div class='small' style='text-transform:uppercase;letter-spacing:.06em;font-weight:700'>{lab}</div>", unsafe_allow_html=True)
        entered = []
        for b in bids:
            c = st.columns([2.2, 1.2, 1.2, 3])
            c[0].markdown(f"**{esc(b['carrier_name'])}**")
            rate = c[1].number_input("Rate", min_value=0, step=25, value=int(float(b["rate"])) if b["rate"] else 0, key=f"br{b['id']}", label_visibility="collapsed")
            transit = c[2].text_input("Transit", value=b["transit"] or "", key=f"bt{b['id']}", label_visibility="collapsed", placeholder="2 days")
            notes = c[3].text_input("Notes", value=b["notes"] or "", key=f"bn{b['id']}", label_visibility="collapsed", placeholder="fuel incl., team, valid thru…")
            entered.append({"carrier": b["carrier_name"], "rate": rate, "transit": transit, "notes": notes, "winner": db.as_bool(b["winner"])})
        c = st.columns([2.2, 1.2, 1.2, 3])
        nc = c[0].text_input("Carrier", key=f"nbc{r['id']}", label_visibility="collapsed", placeholder="Add another carrier")
        nr = c[1].number_input("Rate", min_value=0, step=25, value=0, key=f"nbr{r['id']}", label_visibility="collapsed")
        nt = c[2].text_input("Transit", key=f"nbt{r['id']}", label_visibility="collapsed", placeholder="2 days")
        nn = c[3].text_input("Notes", key=f"nbn{r['id']}", label_visibility="collapsed")
        if nc.strip():
            entered.append({"carrier": nc.strip(), "rate": nr, "transit": nt, "notes": nn, "winner": False})
        names = [e["carrier"] for e in entered]
        current = next((e["carrier"] for e in entered if e["winner"]), None)
        use = st.radio("Price from", ["— none yet —"] + names, index=(names.index(current) + 1) if current in names else 0, horizontal=True, key=f"win{r['id']}")
        for e in entered:
            e["winner"] = e["carrier"] == use
        rates = [e["rate"] for e in entered if e["rate"] > 0]
        c1, c2 = st.columns([1, 3])
        if c1.button("Save bids", key=f"sb{r['id']}"):
            db.run("DELETE FROM bids WHERE request_id=%s", (r["id"],))
            for e in entered:
                db.run("INSERT INTO bids (request_id, carrier_name, rate, transit, notes, winner) VALUES (%s,%s,%s,%s,%s,%s)",
                       (r["id"], e["carrier"], (e["rate"] or None), e["transit"], e["notes"], e["winner"]))
            st.toast("Bids saved")
            st.rerun()
        if rates:
            c2.markdown(f'<div class="small" style="padding-top:8px">Low bid <b>{money(min(rates))}</b> · {len(rates)} of {len(entered)} carriers have quoted</div>', unsafe_allow_html=True)

    winner = next((e for e in entered if e["winner"]), None)
    # when the chosen bid changes, push its numbers into the pricing fields
    wkey = f"lastwin{r['id']}"
    wsig = (winner["carrier"], winner["rate"], winner["transit"]) if winner else None
    if st.session_state.get(wkey) != wsig:
        st.session_state[wkey] = wsig
        if winner:
            st.session_state[f"buy{r['id']}"] = float(winner["rate"] or 0)
            st.session_state[f"sc{r['id']}"] = winner["carrier"]
            st.session_state[f"st{r['id']}"] = winner["transit"]
    with st.expander("3 · Price back to sales", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        default_buy = float(winner["rate"]) if winner and winner["rate"] else (float(r["buy_rate"]) if r.get("buy_rate") else 0.0)
        buy = c1.number_input("Carrier buy rate ($)", min_value=0.0, step=25.0, value=default_buy, key=f"buy{r['id']}")
        mp = c2.number_input("Margin %", min_value=0.0, step=0.5, value=float(r["margin_pct"]) if r.get("margin_pct") is not None else 10.0, key=f"mp{r['id']}")
        ma = c3.number_input("+ flat $", min_value=0.0, step=5.0, value=float(r["margin_amt"]) if r.get("margin_amt") is not None else 0.0, key=f"ma{r['id']}")
        sell = round(buy * (1 + mp / 100) + ma) if buy else 0
        per_lb = f"${sell / float(r['lbs']):.3f} / lb" if sell and r.get("lbs") else ""
        c4.markdown(f'<div class="stat"><div class="l">Sell rate to sales</div><div class="v" style="color:#1F7A4D">{money(sell) if sell else "—"}</div><div class="s">{per_lb}</div></div>', unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        carrier = c1.text_input("Carrier on the quote", value=(winner["carrier"] if winner else (r.get("sell_carrier") or "")), key=f"sc{r['id']}")
        transit = c2.text_input("Transit", value=(winner["transit"] if winner else (r.get("sell_transit") or "")), key=f"st{r['id']}")
        snotes = c3.text_input("Notes to sales (optional)", value=r.get("sell_notes") or "", key=f"sn{r['id']}", placeholder="Rate valid through…, fuel included, 24h appt…")
        if st.button("Post price to sales", key=f"pp{r['id']}", type="primary", disabled=not sell):
            db.run(
                """UPDATE requests SET status='quoted', buy_rate=%s, margin_pct=%s, margin_amt=%s, sell_rate=%s,
                   sell_carrier=%s, sell_transit=%s, sell_notes=%s, quoted_at=%s, quoted_by=%s WHERE id=%s""",
                (buy, mp, ma, sell, carrier.strip(), transit.strip(), snotes.strip(), db.now(), u["id"], r["id"]),
            )
            st.session_state.pop(f"revise{r['id']}", None)
            st.toast("Price posted — sales can see it now")
            st.rerun()


def price_panel(r, u, can_edit: bool):
    per_lb = f"${float(r['sell_rate']) / float(r['lbs']):.3f}" if r.get("sell_rate") and r.get("lbs") else "—"
    label = "Booked" if r["status"] == "booked" else "Price for sales"
    st.markdown(
        f'<div class="small" style="text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin-top:6px">{label}</div>'
        f'<div style="display:flex;gap:22px;align-items:flex-end;flex-wrap:wrap">'
        f'<div class="price">{money(r["sell_rate"])} <span class="small">all-in</span></div>'
        + (f'<div class="kv">Carrier<b>{esc(r["sell_carrier"])}</b></div>' if r.get("sell_carrier") else "")
        + (f'<div class="kv">Transit<b>{esc(r["sell_transit"])}</b></div>' if r.get("sell_transit") else "")
        + f'<div class="kv">Per lb<b>{per_lb}</b></div>'
        + (f'<div class="kv">Buy / margin<b>{money(r["buy_rate"])} · {money(float(r["sell_rate"]) - float(r["buy_rate"]))}</b></div>' if can_edit and r.get("buy_rate") else "")
        + "</div>"
        + (f'<div style="margin-top:6px">{esc(r["sell_notes"])}</div>' if r.get("sell_notes") else "")
        + f'<div class="small">Priced by {esc(user_name(r["quoted_by"]))} · {ago(r["quoted_at"])}</div>',
        unsafe_allow_html=True,
    )
    subject, body = price_text(r)
    req = db.fetchone("SELECT email, name FROM users WHERE id=%s", (r["requester_id"],))
    c1, c2, c3, c4 = st.columns([1.4, 1.2, 1, 2.4])
    if req and can_edit:
        c1.link_button(f"✉ Email {req['name'].split()[0]}", mailto(req["email"], subject, body))
    if r["status"] == "quoted":
        if c2.button("Mark booked", key=f"bk{r['id']}", type="primary"):
            db.run("UPDATE requests SET status='booked', booked_at=%s WHERE id=%s", (db.now(), r["id"]))
            st.rerun()
    elif can_edit:
        if c2.button("Back to priced", key=f"ub{r['id']}"):
            db.run("UPDATE requests SET status='quoted', booked_at=NULL WHERE id=%s", (r["id"],))
            st.rerun()
    if can_edit and c3.button("Revise", key=f"rv{r['id']}"):
        st.session_state[f"revise{r['id']}"] = True
        st.rerun()


def page_queue(u):
    is_freight = u["role"] in ("freight", "admin")
    rows = db.fetchall("SELECT * FROM requests ORDER BY created_at DESC LIMIT 500")
    counts = {k: 0 for k in STATUS}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    tats = []
    for r in rows:
        q, c = to_dt(r.get("quoted_at")), to_dt(r.get("created_at"))
        if q and c and (datetime.now(timezone.utc) - q).days <= 30 and r["status"] in ("quoted", "booked"):
            tats.append((q - c).total_seconds() / 3600)
    s1, s2, s3, s4 = st.columns(4)
    for col, (lab, val, sub) in zip(
        (s1, s2, s3, s4),
        [("New", counts["open"], "RFQ not sent yet"), ("RFQ out", counts["rfq_sent"], "waiting on carriers"),
         ("Priced", counts["quoted"], "back to sales, not booked"),
         ("Avg. turnaround", f"{sum(tats)/len(tats):.1f} h" if tats else "–", "request → price, last 30 days")],
    ):
        col.markdown(f'<div class="stat"><div class="l">{lab}</div><div class="v">{val}</div><div class="s">{sub}</div></div>', unsafe_allow_html=True)
    st.write("")
    f1, f2 = st.columns([3, 1.4])
    labels = {"all": f"All ({len(rows)})", "open": f"New ({counts['open']})", "rfq_sent": f"RFQ out ({counts['rfq_sent']})",
              "quoted": f"Priced ({counts['quoted']})", "booked": f"Booked ({counts['booked']})", "declined": f"Can't cover ({counts['declined']})", "mine": "Mine"}
    pick = f1.radio("Show", list(labels.values()), horizontal=True, label_visibility="collapsed")
    flt = [k for k, v in labels.items() if v == pick][0]
    q = f2.text_input("Search", placeholder="Search lane, customer, PO, ref…", label_visibility="collapsed").strip().lower()

    shown = 0
    for r in rows:
        if flt == "mine" and r["requester_id"] != u["id"]:
            continue
        if flt not in ("all", "mine") and r["status"] != flt:
            continue
        if q and q not in " ".join(str(r.get(k) or "") for k in ("ref", "origin", "dest", "customer", "po", "product", "notes", "sell_carrier")).lower():
            continue
        shown += 1
        with st.container(border=True):
            request_header(r)
            revising = st.session_state.get(f"revise{r['id']}", False)
            if r["status"] == "open":
                if is_freight:
                    step_rfq(r, u)
                else:
                    st.markdown('<div class="small">Waiting for the freight desk to send the RFQ.</div>', unsafe_allow_html=True)
                    notify_button(r, label="✉ Nudge freight desk", key=f"nudge{r['id']}")
            elif r["status"] == "rfq_sent":
                rfq_summary(r)
                if is_freight:
                    step_bids_and_price(r, u)
                else:
                    st.markdown('<div class="small">RFQ is out — the price will show here when the freight desk posts it.</div>', unsafe_allow_html=True)
            elif r["status"] in ("quoted", "booked"):
                if r.get("rfq_sent_at"):
                    rfq_summary(r)
                if revising and is_freight:
                    step_bids_and_price(r, u)
                    if st.button("Cancel revision", key=f"cr{r['id']}"):
                        st.session_state.pop(f"revise{r['id']}", None)
                        st.rerun()
                else:
                    price_panel(r, u, is_freight)
            elif r["status"] == "declined":
                st.markdown(f'<div class="small" style="text-transform:uppercase;letter-spacing:.08em;font-weight:700">Freight desk can\'t cover</div>{esc(r["decline_note"] or "No carrier available for this lane / date.")}'
                            f'<div class="small">{esc(user_name(r["quoted_by"]))} · {ago(r["quoted_at"])}</div>', unsafe_allow_html=True)
                if is_freight and st.button("Reopen", key=f"ro{r['id']}"):
                    db.run("UPDATE requests SET status='open', decline_note='', quoted_at=NULL, quoted_by=NULL WHERE id=%s", (r["id"],))
                    st.rerun()
            if u["role"] == "admin" or (r["requester_id"] == u["id"] and r["status"] == "open"):
                if st.button("Delete request", key=f"del{r['id']}", help="Removes it for everyone"):
                    db.run("DELETE FROM requests WHERE id=%s", (r["id"],))
                    st.rerun()
    if not shown:
        st.info("Nothing here yet." if not rows else "Nothing matches that filter.")


def page_carriers(u):
    st.subheader("Carrier list")
    st.caption("The freight desk picks from this list when sending an RFQ.")
    with st.form("add_carrier", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Carrier / broker")
        email = c2.text_input("RFQ email")
        notes = c3.text_input("Notes (optional)", placeholder="Reefer only, Midwest lanes, contact…")
        if st.form_submit_button("Add carrier", type="primary"):
            if not name.strip() or "@" not in email:
                st.error("Carrier name and a valid email are required.")
            else:
                db.run("INSERT INTO carriers (name, email, notes) VALUES (%s,%s,%s)", (name.strip(), email.strip().lower(), notes.strip()))
                st.rerun()
    for c in db.fetchall("SELECT * FROM carriers ORDER BY active DESC, name"):
        with st.container(border=True):
            a, b, c3, d, e = st.columns([2, 2.4, 3, 1, 1])
            a.markdown(f"**{esc(c['name'])}**" + ("" if db.as_bool(c["active"]) else " <span class='small'>(paused)</span>"), unsafe_allow_html=True)
            b.markdown(esc(c["email"]))
            c3.markdown(f'<span class="small">{esc(c["notes"])}</span>', unsafe_allow_html=True)
            if d.button("Resume" if not db.as_bool(c["active"]) else "Pause", key=f"cp{c['id']}"):
                db.run("UPDATE carriers SET active=%s WHERE id=%s", (not db.as_bool(c["active"]), c["id"]))
                st.rerun()
            if e.button("Delete", key=f"cd{c['id']}"):
                db.run("DELETE FROM carriers WHERE id=%s", (c["id"],))
                st.rerun()


def page_users(u):
    st.subheader("Users")
    st.caption("Sales can submit requests and see prices. Freight can also send RFQs, log bids and price. Admin can also manage users.")
    with st.form("add_user", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([2, 2.4, 1.3, 1.6])
        name = c1.text_input("Name")
        email = c2.text_input("Email")
        role = c3.selectbox("Role", ["sales", "freight", "admin"])
        temp = c4.text_input("Temporary password", help="They'll be asked to change it on first sign-in")
        if st.form_submit_button("Add user", type="primary"):
            if not name.strip() or "@" not in email or len(temp) < 6:
                st.error("Name, a valid email and a temporary password of at least 6 characters are required.")
            elif db.fetchone("SELECT id FROM users WHERE email=%s", (email.lower().strip(),)):
                st.error("That email already has an account.")
            else:
                db.run("INSERT INTO users (email, name, role, password_hash, must_change) VALUES (%s,%s,%s,%s,%s)",
                       (email.lower().strip(), name.strip(), role, hash_pw(temp), True))
                st.success(f"Added {name}. Give them the temporary password — they'll set their own on first sign-in.")
                st.rerun()
    for x in db.fetchall("SELECT * FROM users ORDER BY role, name"):
        with st.container(border=True):
            a, b, c, d, e = st.columns([2, 2.6, 1.2, 1.4, 1.2])
            a.markdown(f"**{esc(x['name'])}**" + ("" if db.as_bool(x["active"]) else " <span class='small'>(deactivated)</span>"), unsafe_allow_html=True)
            b.markdown(esc(x["email"]))
            c.markdown(x["role"])
            if x["id"] != u["id"]:
                if d.button("Reset password", key=f"rp{x['id']}"):
                    st.session_state[f"resetting{x['id']}"] = True
                if e.button("Deactivate" if db.as_bool(x["active"]) else "Reactivate", key=f"da{x['id']}"):
                    db.run("UPDATE users SET active=%s WHERE id=%s", (not db.as_bool(x["active"]), x["id"]))
                    st.rerun()
                if st.session_state.get(f"resetting{x['id']}"):
                    t = st.text_input("New temporary password", key=f"tp{x['id']}")
                    if st.button("Save", key=f"ts{x['id']}") and len(t) >= 6:
                        db.run("UPDATE users SET password_hash=%s, must_change=%s WHERE id=%s", (hash_pw(t), True, x["id"]))
                        st.session_state.pop(f"resetting{x['id']}", None)
                        st.success("Reset — they'll be asked to choose a new one on sign-in.")
                        st.rerun()


# ----------------------------------------------------------------------------- main
def main():
    try:
        bootstrap_admin()
    except Exception as e:  # database not reachable
        st.error("Can't reach the database. Check DATABASE_URL in the app's secrets.")
        st.caption(str(e))
        st.stop()

    u = current_user()
    if not u:
        login_screen()
        return
    header(u)
    if db.as_bool(u["must_change"]):
        change_password_screen(u, forced=True)
        return

    pages = ["New request", "Queue"]
    if u["role"] in ("freight", "admin"):
        pages.append("Carriers")
    if u["role"] == "admin":
        pages.append("Users")
    pages.append("My account")
    with st.sidebar:
        st.markdown(f"**{u['name']}**  \n<span class='small'>{u['email']}</span>", unsafe_allow_html=True)
        page = st.radio("Go to", pages, label_visibility="collapsed")
        if st.button("Sign out"):
            st.session_state.pop("user", None)
            st.rerun()
        st.caption("Third Generation Food Company")

    if page == "New request":
        page_new_request(u)
    elif page == "Queue":
        page_queue(u)
    elif page == "Carriers":
        page_carriers(u)
    elif page == "Users":
        page_users(u)
    else:
        change_password_screen(u)


main()
