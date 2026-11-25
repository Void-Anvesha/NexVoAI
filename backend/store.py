"""Small SQLite repository for the demo clinic."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

DB = os.getenv("DATABASE_PATH", "./careline.db")


@contextmanager
def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS doctors(id TEXT PRIMARY KEY, name TEXT, specialty TEXT, initials TEXT, color TEXT, experience TEXT);
        CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY AUTOINCREMENT, doctor_id TEXT, day TEXT, time TEXT, booked INTEGER DEFAULT 0, FOREIGN KEY(doctor_id) REFERENCES doctors(id));
        CREATE TABLE IF NOT EXISTS appointments(id TEXT PRIMARY KEY, doctor_id TEXT, slot_id INTEGER, patient_phone TEXT, day TEXT, time TEXT, status TEXT DEFAULT 'booked', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(doctor_id) REFERENCES doctors(id));
        """)
        # Existing databases predate the patient name column; add it in place.
        columns = {r[1] for r in db.execute("PRAGMA table_info(appointments)")}
        if "patient_name" not in columns:
            db.execute("ALTER TABLE appointments ADD COLUMN patient_name TEXT")
        if db.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0:
            doctors = [
                ("maya-shah", "Dr. Maya Shah", "Cardiology", "MS", "#dbeafe", "12 years"),
                ("aarav-mehta", "Dr. Aarav Mehta", "Dermatology", "AM", "#fce7f3", "9 years"),
                ("leena-iyer", "Dr. Leena Iyer", "General medicine", "LI", "#dcfce7", "15 years"),
                ("kabir-rao", "Dr. Kabir Rao", "Orthopedics", "KR", "#fef3c7", "11 years"),
            ]
            db.executemany("INSERT INTO doctors VALUES(?,?,?,?,?,?)", doctors)
            for doctor_id, *_ in doctors:
                for offset in range(1, 6):
                    day = (date.today() + timedelta(days=offset)).isoformat()
                    for time in ("09:30", "11:00", "14:30", "16:00"):
                        db.execute("INSERT INTO slots(doctor_id,day,time) VALUES(?,?,?)", (doctor_id, day, time))


def doctors_with_slots():
    with connect() as db:
        doctors = db.execute("SELECT * FROM doctors ORDER BY name").fetchall()
        result = []
        for d in doctors:
            slots = db.execute("SELECT id, day, time FROM slots WHERE doctor_id=? AND booked=0 ORDER BY day,time", (d["id"],)).fetchall()
            result.append({**dict(d), "slots": [dict(s) for s in slots]})
        return result


def appointments():
    with connect() as db:
        rows = db.execute("""SELECT a.id,a.patient_name,a.patient_phone,a.day,a.time,a.status,d.name doctor,d.specialty
            FROM appointments a JOIN doctors d ON d.id=a.doctor_id ORDER BY a.created_at DESC""").fetchall()
        return [dict(r) for r in rows]


# Callers say "dermatologist", "skin doctor" or "Dr. Mehta", not the exact
# specialty string, so map everyday words to each specialty.
SPECIALTY_WORDS = {
    "Cardiology": ("cardio", "heart", "chest", "blood pressure"),
    "Dermatology": ("derma", "skin", "rash", "acne", "hair"),
    "General medicine": ("general", "physician", "gp", "family", "fever", "cold", "checkup", "check-up"),
    "Orthopedics": ("ortho", "bone", "joint", "knee", "back", "fracture", "spine"),
}
FILLER_WORDS = {"dr", "doctor", "doc", "a", "the", "any", "for", "specialist", "with"}


def match_doctor_ids(db, term: str) -> list[str]:
    """Return ids of doctors matching a name, specialty or everyday phrase.
    An empty term matches every doctor."""
    doctors = db.execute("SELECT id, name, specialty FROM doctors").fetchall()
    term = (term or "").lower().replace(".", " ").strip()
    if not term:
        return [d["id"] for d in doctors]
    words = [w for w in term.replace("-", " ").split() if w not in FILLER_WORDS]
    matched = []
    for d in doctors:
        name_words = d["name"].lower().replace(".", " ").split()
        specialty = d["specialty"].lower()
        hints = SPECIALTY_WORDS.get(d["specialty"], ())
        if (
            any(w in name_words for w in words)                      # "Mehta", "Maya"
            or any(w[:5] in specialty for w in words if len(w) >= 5)  # "dermatologist" ~ "dermatology"
            or any(w in specialty for w in words if len(w) >= 4)      # "derm", "ortho"
            or any(h in term for h in hints)                          # "skin doctor"
        ):
            matched.append(d["id"])
    return matched


def check_availability(doctor: str = "", day: str = ""):
    """Open slots as a list of rows (used by the dashboard API)."""
    with connect() as db:
        ids = match_doctor_ids(db, doctor)
        if not ids:
            return []
        query = (
            "SELECT s.id,s.day,s.time,d.id doctor_id,d.name doctor,d.specialty FROM slots s "
            f"JOIN doctors d ON d.id=s.doctor_id WHERE s.booked=0 AND d.id IN ({','.join('?' * len(ids))})"
        )
        params = list(ids)
        if day:
            query += " AND s.day=?"
            params.append(day)
        query += " ORDER BY s.day,s.time"
        return [dict(r) for r in db.execute(query, params).fetchall()]


def availability_for_agent(doctor: str = "", day: str = "") -> dict:
    """Compact availability for the LLM: grouped by doctor and day, short
    enough to read quickly. If the requested day is full, the next open days
    are returned instead, so the agent can offer alternatives in one step."""
    rows = check_availability(doctor, day)
    note = None
    if not rows and day:
        rows = check_availability(doctor, "")
        note = f"No open slots on {day}; showing the next available days instead."
    if not rows:
        with connect() as db:
            specialties = [r[0] for r in db.execute("SELECT DISTINCT specialty FROM doctors")]
        return {"doctors": [], "note": f"No doctor matched '{doctor}'. Available specialties: {', '.join(specialties)}."}
    grouped: dict = {}
    for r in rows:
        doc = grouped.setdefault(r["doctor"], {"doctor": r["doctor"], "specialty": r["specialty"], "days": {}})
        if r["day"] in doc["days"] or len(doc["days"]) < 3:  # next 3 open days per doctor
            doc["days"].setdefault(r["day"], []).append(r["time"])
    result = {"doctors": list(grouped.values())}
    if note:
        result["note"] = note
    return result


def book(doctor: str, day: str, time: str, phone: str, name: str = ""):
    phone = "".join(c for c in phone if c.isdigit() or c == "+")
    name = " ".join(name.split()).title()
    if len("".join(c for c in phone if c.isdigit())) < 7:
        return {"ok": False, "message": "Please provide a phone number with at least seven digits."}
    if not name:
        return {"ok": False, "message": "Please ask the caller for the patient's full name before booking."}
    with connect() as db:
        ids = match_doctor_ids(db, doctor) or [""]
        row = db.execute(f"""SELECT s.id,d.id doctor_id,d.name FROM slots s JOIN doctors d ON d.id=s.doctor_id
            WHERE s.booked=0 AND s.day=? AND s.time=? AND d.id IN ({','.join('?' * len(ids))}) LIMIT 1""",
            (day, time, *ids)).fetchone()
        if not row:
            return {"ok": False, "message": "That slot is no longer available. Please check the current availability."}
        db.execute("UPDATE slots SET booked=1 WHERE id=?", (row["id"],))
        appt_id = f"CL-{date.today():%y%m%d}-{row['id']:04d}"
        db.execute("INSERT INTO appointments(id,doctor_id,slot_id,patient_name,patient_phone,day,time) VALUES(?,?,?,?,?,?,?)", (appt_id,row["doctor_id"],row["id"],name,phone,day,time))
        return {"ok": True, "id": appt_id, "patient_name": name, "doctor": row["name"], "day": day, "time": time}


def _name_matches(stored: str | None, spoken: str) -> bool:
    """Loose match: speech-to-text spells names inconsistently, so any shared
    word (e.g. the first name) counts as a match."""
    stored_words = set((stored or "").lower().split())
    return bool(stored_words & set(spoken.lower().split()))


def cancel(phone: str, name: str = "", appointment_id: str = ""):
    """Cancel an active appointment found by the spoken phone number.
    The patient name (and, if needed, the appointment id) picks the right one
    when several appointments share a number, e.g. family members."""
    digits = "".join(c for c in phone if c.isdigit())
    with connect() as db:
        candidates = [
            r for r in db.execute("SELECT * FROM appointments WHERE status='booked' ORDER BY created_at").fetchall()
            if "".join(c for c in r["patient_phone"] if c.isdigit()) == digits
        ]
        if not candidates:
            return {"ok": False, "message": "I couldn't find an active appointment for that number."}
        if appointment_id:
            candidates = [r for r in candidates if r["id"].lower() == appointment_id.strip().lower()] or candidates
        if name and len(candidates) > 1:
            candidates = [r for r in candidates if _name_matches(r["patient_name"], name)] or candidates
        if len(candidates) > 1:
            return {
                "ok": False,
                "message": "Several active appointments use this number. Ask which one to cancel.",
                "appointments": [
                    {"id": r["id"], "patient_name": r["patient_name"], "day": r["day"], "time": r["time"]}
                    for r in candidates
                ],
            }
        row = candidates[0]
        db.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (row["id"],))
        db.execute("UPDATE slots SET booked=0 WHERE id=?", (row["slot_id"],))
        return {"ok": True, "id": row["id"], "patient_name": row["patient_name"], "day": row["day"], "time": row["time"]}
