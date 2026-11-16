from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import settings
from app.db import engine
from app.main import _tick, app
from app.models import Assignment, AvailabilitySlot, Case, CaseEvent, Notification, utcnow
from app.notify import run_all, run_reminders
from tests.conftest import signup
from tests.test_phase3 import make_role, staff
from tests.test_phase5 import offer, setup_offer, verified_lawyer, admin_client, lawyer_applied
from tests.test_phase6 import accepted, say
from tests.test_requests import post

UTC = timezone.utc


def follow(c, **kw):
    return c.put("/api/me/followup", json=kw)


def count(kind=None):
    with Session(engine) as db:
        q = select(Notification)
        if kind:
            q = q.where(Notification.kind == kind)
        return len(db.exec(q).all())


def reminders(now):
    with Session(engine) as db:
        return run_reminders(db, now)


def user_with_case(client, email="user@example.com"):
    signup(client, email)
    return post(client).json()


# ---------------- follow-up settings ----------------
def test_followup_defaults_and_validation(client):
    signup(client)
    g = client.get("/api/me/followup").json()
    assert g["pref"] == "important_only" and g["channel"] == "in_app" and g["available_channels"] == ["in_app"]
    assert "guarantee nahi" in g["note"]
    assert follow(client, pref="daily", safe_time="08:30", timezone="Asia/Karachi").json()["pref"] == "daily"
    assert follow(client, pref="hourly").status_code == 422
    assert follow(client, safe_time="25:00").status_code == 422
    assert follow(client, safe_time="9:00").status_code == 422
    assert follow(client, timezone="Mars/Base").status_code == 422
    for ch in ("email", "sms", "whatsapp"):  # provider aur consent ke bagair simulate nahi
        r = follow(client, channel=ch)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "channel_unavailable"
    assert client.get("/api/me/followup").json()["safe_time"] == "08:30"
    assert TestClient(app).get("/api/me/followup").status_code == 401


# ---------------- reminders ----------------
def test_daily_reminder_once_per_day_and_survives_restart(client):
    user_with_case(client)
    follow(client, pref="daily", safe_time="09:00")
    early = datetime(2030, 1, 10, 3, 0)  # Karachi 08:00: abhi waqt nahi
    day1 = datetime(2030, 1, 10, 5, 0)  # Karachi 10:00
    assert reminders(early) == 0
    assert reminders(day1) == 1
    assert reminders(day1 + timedelta(hours=3)) == 0  # usi din dobara nahi
    engine.dispose()  # "restart"
    assert reminders(day1 + timedelta(hours=5)) == 0
    assert reminders(day1 + timedelta(days=1)) == 1  # agle din nayi
    assert count("daily_reminder") == 2


def test_no_reminders_for_important_only_off_or_no_open_request(client):
    user_with_case(client)
    day = datetime(2030, 1, 10, 5, 0)
    assert reminders(day) == 0  # default important_only
    follow(client, pref="off")
    assert reminders(day) == 0
    follow(client, pref="daily")
    client.post("/api/requests/1/close")  # khuli request nahi
    assert reminders(day) == 0
    assert count() == 0


def test_daily_content_no_reply_then_activity_and_discreet(client):
    d, lc, pid, coord, aid, _ = setup_offer(client)  # consent de chuka user, offer pending
    follow(client, pref="daily", safe_time="00:00")
    assert reminders(utcnow() - timedelta(days=3)) == 1  # purane din ki reminder: koi activity nahi
    n = client.get("/api/notifications").json()["notifications"]
    rem = [x for x in n if x["kind"] == "daily_reminder"][0]
    assert "Abhi naya jawab nahi aaya" in rem["body"] and "guarantee nahi" in rem["body"]
    for secret in ("plot", "qabza", d["tracking_no"], "Lahore"):
        assert secret not in rem["body"] and secret not in rem["preview"]
    assert rem["preview"] == "Insaf Dastak ka reminder."
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    say(lc, d["tracking_no"], "Salam", "k-rem-00001")
    assert reminders(utcnow() + timedelta(hours=1)) == 1  # ab wakeel ne jawab diya, accept hua
    en = client.get("/api/notifications", headers={"X-Lang": "en"}).json()["notifications"]
    texts = [x["body"] for x in en if x["kind"] == "daily_reminder"]
    assert any("new update" in x for x in texts) and any("No new reply yet" in x for x in texts)


def test_pending_action_text_when_consent_missing(client):
    signup(client)
    post(client)  # ijazat nahi di
    follow(client, pref="daily", safe_time="00:00")
    reminders(utcnow() + timedelta(hours=1))
    body = client.get("/api/notifications").json()["notifications"][0]["body"]
    assert "referral ki ijazat dein" in body


def test_weekly_summary_once_per_week_and_catches_up(client):
    user_with_case(client)
    follow(client, pref="weekly", safe_time="09:00")
    mon_early = datetime(2030, 1, 7, 3, 0)  # Peer, Karachi 08:00
    mon_ok = datetime(2030, 1, 7, 5, 0)  # Peer 10:00
    assert reminders(mon_early) == 0
    assert reminders(mon_ok) == 1
    assert reminders(datetime(2030, 1, 9, 5, 0)) == 0  # usi haftay mein dobara nahi
    assert reminders(datetime(2030, 1, 14, 5, 0)) == 1  # agla hafta
    assert count("weekly_summary") == 2
    body = client.get("/api/notifications").json()["notifications"][0]["body"]
    assert "Is haftay" in body


def test_weekly_catches_up_if_monday_was_missed(client):
    user_with_case(client)
    follow(client, pref="weekly", safe_time="09:00")
    assert reminders(datetime(2030, 1, 8, 7, 0)) == 1  # Mangal ko pehla run: ek hi, kai nahi
    assert reminders(datetime(2030, 1, 8, 9, 0)) == 0


# ---------------- status notifications ----------------
def test_important_updates_always_reach_dashboard_and_only_owner(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    follow(client, pref="off")  # reminders band, par important update phir bhi
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    n = client.get("/api/notifications").json()
    assert n["unread"] == 1 and n["notifications"][0]["kind"] == "status_update"
    first = n["notifications"][0]
    assert d["tracking_no"] not in first["preview"] and first["preview"] == "Aap ki request mein update hai."
    assert "qubool" in first["body"]
    assert len(client.get("/api/notifications").json()["notifications"]) == 1  # dobara dekhne se duplicate nahi
    coord.post(f"/api/coord/assignments/{aid}/revoke")
    kinds = [x["body"] for x in client.get("/api/notifications").json()["notifications"]]
    assert len(kinds) == 2 and any("coordinator ki queue" in k for k in kinds)
    other = TestClient(app)
    signup(other, "stranger@example.com")
    assert other.get("/api/notifications").json()["notifications"] == []
    assert lc.get("/api/notifications").json()["notifications"] == []  # wakeel ko user ke updates nahi


def test_mark_read_and_ownership(client):
    d, lc, pid, coord, aid, _ = setup_offer(client)
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    nid = client.get("/api/notifications").json()["notifications"][0]["id"]
    other = TestClient(app)
    signup(other, "stranger@example.com")
    assert other.post(f"/api/notifications/{nid}/read").status_code == 404
    assert client.post(f"/api/notifications/{nid}/read").json()["read"] is True
    assert client.get("/api/notifications").json()["unread"] == 0
    assert client.post("/api/notifications/read-all").json() == {"ok": True}


# ---------------- jobs aur scheduler ----------------
def test_admin_job_run_expires_offer_without_any_user_action(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    with Session(engine) as db:
        a = db.get(Assignment, aid)
        a.expires_at = utcnow() - timedelta(hours=1)
        db.add(a)
        db.commit()
    assert coord.post("/api/admin/jobs/run").status_code == 403
    assert client.post("/api/admin/jobs/run").status_code == 403
    r = admin.post("/api/admin/jobs/run")
    assert r.status_code == 200 and r.json()["offers_expired"] == 1
    with Session(engine) as db:
        assert db.get(Assignment, aid).status == "expired"
    assert admin.post("/api/admin/jobs/run").json()["offers_expired"] == 0  # dobara chalane se kuch dohrata nahi


def test_run_all_twice_makes_no_duplicates(client):
    d, lc, pid, coord, aid, _ = setup_offer(client)
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    follow(client, pref="daily", safe_time="00:00")
    now = utcnow() + timedelta(hours=1)
    with Session(engine) as db:
        a, b = run_all(db, now), run_all(db, now)
    assert a["status_notifications"] == 1 and a["reminders"] == 1
    assert b == {"offers_expired": 0, "status_notifications": 0, "reminders": 0,
                 "sessions_deleted": 0, "cases_purged": 0}


def test_scheduler_starts_and_stops_and_tick_runs(client, monkeypatch):
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(settings, "scheduler_interval_seconds", 3600)
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
    _tick()  # seedha bhi chal jata hai


# ---------------- coordinator reports ----------------
def test_coordinator_reports_have_counts_not_personal_details(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    with Session(engine) as db:
        c = db.exec(select(Case)).one()
        c.created_at = utcnow() - timedelta(days=9)
        db.add(c)
        db.commit()
    day = coord.get("/api/coord/reports/daily")
    assert day.status_code == 200
    j = day.json()
    assert j["unassigned_count"] == 1 and j["overdue_count"] == 1 and j["unassigned"][0]["offer_pending"] is True
    wk = coord.get("/api/coord/reports/weekly").json()
    assert wk["pending_requests"] == 1 and wk["pending_by_category"] == {"property": 1}
    assert wk["lawyer_workload"][0]["active_cases"] == 1
    for text in (day.text, coord.get("/api/coord/reports/weekly").text):
        for secret in ("user@example.com", "lawyer@example.com", "qabza", "summary", "statement", "@"):
            assert secret not in text
    for c in (client, lc, TestClient(app)):
        assert c.get("/api/coord/reports/daily").status_code in (401, 403)
        assert c.get("/api/coord/reports/weekly").status_code in (401, 403)


# ---------------- availability ----------------
def day_at(days, hour=10, minutes=60):
    s = (datetime.now(UTC) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return s.isoformat(), (s + timedelta(minutes=minutes)).isoformat()


def publish(c, days=2, hour=10, **kw):
    s, e = day_at(days, hour)
    return c.post("/api/lawyer/availability", json={"start": s, "end": e, **kw})


def test_availability_roles_and_validation(client):
    signup(client, "user@example.com")
    admin = admin_client()
    lc, pid = verified_lawyer(admin)
    pending, _ = lawyer_applied("pending@example.com", "SB-111")
    assert publish(client).status_code == 403
    assert publish(pending).status_code == 403
    assert publish(lc).status_code == 201
    assert publish(lc).status_code == 409  # wahi waqt: takrao
    s, e = day_at(2, 10, 5)
    for body in ({"start": s, "end": e},  # 5 minute
                 {"start": day_at(2, 10, 300)[0], "end": day_at(2, 10, 300)[1]},  # 5 ghante
                 {"start": day_at(-1)[0], "end": day_at(-1)[1]},  # guzra hua
                 {"start": day_at(90)[0], "end": day_at(90)[1]},  # 60 din se aage
                 {"start": "kal subah", "end": "parson"},
                 {"start": day_at(3)[1], "end": day_at(3)[0]}):  # end pehle
        assert lc.post("/api/lawyer/availability", json=body).status_code == 422
    assert publish(lc, days=3, repeat="monthly").status_code == 422
    assert publish(lc, days=3, repeat="daily", repeat_count=15).status_code == 422
    assert publish(lc, days=3, repeat="weekly", repeat_count=9).status_code == 422


def test_daily_and_weekly_repeat_all_or_nothing(client):
    admin = admin_client()
    lc, pid = verified_lawyer(admin)
    r = publish(lc, days=3, repeat="daily", repeat_count=3)
    assert r.status_code == 201 and len(r.json()["slots"]) == 3
    r = publish(lc, days=10, repeat="weekly", repeat_count=2)
    assert r.status_code == 201 and len(r.json()["slots"]) == 2
    before = len(lc.get("/api/lawyer/availability").json()["slots"])
    assert publish(lc, days=4, hour=10, repeat="daily", repeat_count=3).status_code == 409  # beech mein takrao
    assert len(lc.get("/api/lawyer/availability").json()["slots"]) == before  # kuch nahi bana


def test_naive_time_is_read_in_users_timezone(client):
    admin = admin_client()
    lc, pid = verified_lawyer(admin)
    day = (datetime.now(UTC) + timedelta(days=2)).date().isoformat()
    r = lc.post("/api/lawyer/availability", json={"start": f"{day}T15:00:00", "end": f"{day}T16:00:00"})
    s = r.json()["slots"][0]
    assert s["start_local"].startswith(f"{day}T15:00") and s["start_local"].endswith("+05:00")
    assert s["start"].startswith(f"{day}T10:00")


def booked_setup(client):
    d, lc, pid, coord, aid, admin = accepted(client)
    lc.post("/api/lawyer/availability", json=dict(zip(("start", "end"), day_at(2))))
    lc.post("/api/lawyer/availability", json=dict(zip(("start", "end"), day_at(3))))
    slots = client.get(f"/api/cases/{d['tracking_no']}/slots").json()
    return d, lc, pid, coord, aid, admin, slots


def test_user_sees_only_own_lawyers_open_slots_after_acceptance(client):
    d, lc, pid, coord, aid, admin = setup_offer(client)
    lc.post("/api/lawyer/availability", json=dict(zip(("start", "end"), day_at(2))))
    tn = d["tracking_no"]
    assert client.get(f"/api/cases/{tn}/slots").json() == {"open_slots": [], "my_booking": None}
    assert client.post(f"/api/cases/{tn}/slots/1/book").status_code == 404  # wakeel abhi accept nahi
    lc.post(f"/api/lawyer/offers/{aid}/accept")
    other_lawyer, _ = verified_lawyer(admin, "other@example.com", "SB-999")
    other_lawyer.post("/api/lawyer/availability", json=dict(zip(("start", "end"), day_at(4))))
    slots = client.get(f"/api/cases/{tn}/slots").json()["open_slots"]
    assert len(slots) == 1  # doosre wakeel ka slot nahi
    with Session(engine) as db:
        foreign = [s.id for s in db.exec(select(AvailabilitySlot)).all() if s.id != slots[0]["id"]][0]
    assert client.post(f"/api/cases/{tn}/slots/{foreign}/book").status_code == 404


def test_booking_flow_and_everyone_else_is_blocked(client):
    d, lc, pid, coord, aid, admin, slots = booked_setup(client)
    tn = d["tracking_no"]
    s1, s2 = (x["id"] for x in slots["open_slots"])
    stranger = TestClient(app)
    signup(stranger, "stranger@example.com")
    assert stranger.get(f"/api/cases/{tn}/slots").status_code == 404
    assert stranger.post(f"/api/cases/{tn}/slots/{s1}/book").status_code == 404
    assert lc.post(f"/api/cases/{tn}/slots/{s1}/book").status_code == 403  # wakeel khud book nahi karta
    assert TestClient(app).post(f"/api/cases/{tn}/slots/{s1}/book").status_code == 401
    r = client.post(f"/api/cases/{tn}/slots/{s1}/book")
    assert r.status_code == 200 and r.json()["status"] == "booked"
    mine = client.get(f"/api/cases/{tn}/slots").json()
    assert mine["my_booking"]["id"] == s1 and [x["id"] for x in mine["open_slots"]] == [s2]
    assert client.post(f"/api/cases/{tn}/slots/{s2}/book").status_code == 409  # ek request, ek slot
    booked = [s for s in lc.get("/api/lawyer/availability").json()["slots"] if s["status"] == "booked"]
    assert booked[0]["booked_tracking_no"] == tn
    assert count("slot_booked") == 1
    assert "consultation" in client.get(f"/api/requests/{d['id']}").json()


def test_no_double_booking_across_requests(client):
    d, lc, pid, coord, aid, admin, slots = booked_setup(client)
    s1 = slots["open_slots"][0]["id"]
    d2 = post(client, key="case-two-00001").json()
    client.put(f"/api/requests/{d2['id']}/consent", json={"referral": True})
    aid2 = offer(coord, d2["tracking_no"], pid).json()["assignment_id"]
    lc.post(f"/api/lawyer/offers/{aid2}/accept")
    assert client.post(f"/api/cases/{d['tracking_no']}/slots/{s1}/book").status_code == 200
    r = client.post(f"/api/cases/{d2['tracking_no']}/slots/{s1}/book")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "slot_taken"
    with Session(engine) as db:
        s = db.get(AvailabilitySlot, s1)
        assert s.status == "booked" and s.booked_request_id == d["id"]


def test_user_unbook_and_lawyer_cancel_notify_the_other_side(client):
    d, lc, pid, coord, aid, admin, slots = booked_setup(client)
    tn, s1 = d["tracking_no"], slots["open_slots"][0]["id"]
    client.post(f"/api/cases/{tn}/slots/{s1}/book")
    assert client.delete(f"/api/cases/{tn}/slots/{s1}/book").status_code == 200
    assert count("slot_released") == 1
    assert len(client.get(f"/api/cases/{tn}/slots").json()["open_slots"]) == 2
    client.post(f"/api/cases/{tn}/slots/{s1}/book")
    assert lc.delete(f"/api/lawyer/availability/{s1}").status_code == 200
    assert lc.delete(f"/api/lawyer/availability/{s1}").status_code == 409
    bodies = [n["body"] for n in client.get("/api/notifications").json()["notifications"]]
    assert any("mansookh" in b for b in bodies)
    assert client.get(f"/api/cases/{tn}/slots").json()["my_booking"] is None


def test_slot_reopens_when_lawyer_access_is_removed(client):
    d, lc, pid, coord, aid, admin, slots = booked_setup(client)
    tn, s1 = d["tracking_no"], slots["open_slots"][0]["id"]
    client.post(f"/api/cases/{tn}/slots/{s1}/book")
    coord.post(f"/api/coord/assignments/{aid}/revoke")
    with Session(engine) as db:
        s = db.get(AvailabilitySlot, s1)
        assert s.status == "open" and s.booked_request_id is None
    assert client.get(f"/api/cases/{tn}/slots").json() == {"open_slots": [], "my_booking": None}


def test_everything_survives_restart(client):
    d, lc, pid, coord, aid, admin, slots = booked_setup(client)
    tn, s1 = d["tracking_no"], slots["open_slots"][0]["id"]
    client.post(f"/api/cases/{tn}/slots/{s1}/book")
    follow(client, pref="weekly", safe_time="07:30")
    engine.dispose()
    with TestClient(app) as fresh:
        fresh.post("/api/auth/login", json={"email": "user@example.com", "password": "strongpass1"})
        assert fresh.get(f"/api/cases/{tn}/slots").json()["my_booking"]["id"] == s1
        g = fresh.get("/api/me/followup").json()
        assert g["pref"] == "weekly" and g["safe_time"] == "07:30"
        assert len(fresh.get("/api/notifications").json()["notifications"]) >= 1
