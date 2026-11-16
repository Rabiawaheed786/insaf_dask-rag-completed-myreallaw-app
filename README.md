# Insaf Dastak: Phase 0 se 9 (backend + RAG) + poora frontend (cumulative)

Kya hai: FastAPI backend, SQLite database, signup/login/logout, server-side sessions,
Roman Urdu / English messages, Alembic migrations (0001 se 0008), 140 tests.
Phase 2: request likhna, user ka approve kiya hua summary, tracking number (save ke baad),
retry par duplicate nahi (Idempotency-Key), 'wakeel nahi mila' fallback, verified contacts,
summary download, coordinator ki unassigned queue.
Phase 3: user ki referral ijazat (consent), coordinator ka referral record (delivered sirf
acknowledgment reference ke saath, failed sirf wajah ke saath), overdue queue (7 din), alternatives,
request band karna, admin ke verified contacts aur roles, audit log.
Phase 4: optional AI (Gemini REST): clarifying sawal aur summary draft, user ki ijazat ke saath,
email/phone/CNIC/IBAN/lambe numbers hata kar bhejna, ghante ki hadd, AI fail ho to manual submission.
Phase 5: wakeel ki arzi, admin verification (shakhsiyat + registration + source note), suspend/reject,
coordinator ka offer (user ki ijazat zaroori), meead (default 3 din), accept/decline, access sirf accepted
case par, revoke/reassign; ijazat wapas, request band ya wakeel suspend hone par access foran band.
Phase 6: private chat (user aur accepted wakeel), private files (PDF/JPG/PNG, 5 MB, random name,
web par kabhi serve nahi), authorised download, summary download.
Phase 7: follow-up pasand (daily/weekly/important_only/off, safe time, timezone), in-app reminders
aur haftawar khulasa (duplicate nahi, restart ke baad bhi), important updates dashboard par hamesha,
scheduler, offer ki meead waqt par khatam, coordinator ki daily/weekly reports, wakeel ki availability
(daily/weekly dohrana) aur user ki slot booking (double booking nahi).
Phase 8: foran madad (/api/emergency), bachon ke cases ka review gate, CSRF origin check, CSP aur
security headers, IP hadd, password badalna, admin CLI (reset-password, revoke-sessions), backup/restore,
retention (khud mitana), apna data export aur account mitana, end-to-end tests, docs/ (incident, privacy, tayyari).
Kya nahi hai abhi: email/SMS/WhatsApp, files, reminders, AI, asli frontend.

## Python ka version (zaroori)
Yeh project Python 3.11 se 3.13 par chalta hai. Python 3.14 par sqlmodel 0.0.22 ruk jata hai
(error: Field 'id' requires a type annotation). .python-version file uv ko 3.13 chunne ko kehti hai;
agar aap ke paas 3.13 nahi to uv usay khud download kar leta hai (lagbhag 100 MB).

## Frontend (poora): browser mein kaise dekhein
Server chalayein (`uv run uvicorn app.main:app --reload`) aur browser mein kholein: http://127.0.0.1:8000
(`static\index.html` ko seedha double-click karke na kholein: woh server ke bagair kaam nahi karta).
Pehle "Naya account banayein" se account banayein (har naye folder ka database khali hota hai).
Screens: home, login, signup, foran madad, dashboard, naya masla (AI madad ke saath, agar on ho), request ki tafseel
(ijazat, band karna, summary download, timeline), chat, files, mashware ka waqt (slots), notifications, settings
(follow-up, password, data export, account mitana), wakeel ka panel (arzi, offers, cases, availability),
coordinator ka panel (reports, assign, referral), admin ka panel (wakeel verify, contacts, bachon ka review, roles, jobs).
Har page par Roman Urdu/English ka button, "Foran madad" aur "Screen chhupayein".
Files: static/index.html, static/css/app.css, static/js/*.js, static/i18n/ur.json aur en.json.
Pehla admin: `uv run python -m app.cli make-admin aapka@email.com` (phir admin panel se coordinator banayein).

## Windows par chalane ke qadam (PowerShell)

1. uv install (agar nahi hai):
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   Phir PowerShell band karke dobara kholein, aur `uv --version` chala kar check karein.
2. Zip ko extract karein, phir folder mein jayein:
   cd C:\path\to\insaf-dastak
3. Settings file banayein:
   copy .env.example .env
4. Dependencies install (uv Python bhi khud la sakta hai):
   uv sync
5. Database tables banayein:
   uv run alembic upgrade head
6. Tests chalayein:
   uv run pytest -q
7. Server chalayein:
   uv run uvicorn app.main:app --reload
8. Browser mein kholein: http://127.0.0.1:8000  aur  http://127.0.0.1:8000/docs

## API (abhi)
GET /api/categories, GET /api/official-contacts?province=,
POST /api/requests (header Idempotency-Key zaroori), GET /api/requests, GET /api/requests/{id},
GET /api/requests/{id}/summary.txt, GET /api/coord/queue (sirf coordinator/admin)
POST /api/auth/signup, POST /api/auth/login, POST /api/auth/logout,
GET /api/auth/me, PUT /api/auth/me/language, GET /api/health
Error ki zaban: header `X-Lang: en` ya `X-Lang: roman_urdu`.

## Pehla admin banana (Phase 3)
1. App mein /docs par signup karein.
2. CMD mein: uv run python -m app.cli make-admin aapka@email.com
3. Admin phir /api/admin/users/role se doosre user ko coordinator bana sakta hai,
   aur /api/admin/contacts se verified contacts jor sakta hai (https source aur tareekh zaroori).

## Naya (Phase 3) API
PUT /api/requests/{id}/consent, POST /api/requests/{id}/close,
GET /api/coord/queue, GET /api/coord/requests/{tracking_no},
POST /api/coord/requests/{tracking_no}/referrals (header Idempotency-Key zaroori),
POST /api/admin/contacts, PUT /api/admin/users/role

## Phase 4: AI (admin-managed key / BYOK)
1. Coordinator ya admin dashboard kholein: "AI Configuration" card mein provider (Gemini, OpenAI ya
   DeepSeek), model (khali chhodein to provider ka default) aur API key save karein. Key DB mein
   encrypt ho kar jati hai; screen aur API par sirf masked shakal (jaise sk-...1234) dikhti hai.
2. .env mein AI_KEY_SECRET set karein (kam az kam 32 harf ka random secret). Isi secret se keys
   encrypt hoti hain; secret badalne par purani keys decrypt nahi hongi aur dobara save karni parhengi.
3. Fallback: DB mein key na ho to purana .env raasta chalta hai (AI_ENABLED=true, AI_API_KEY=...,
   AI_MODEL=..., AI_TIER=...). Asli istemal ke liye admin panel hi behtar hai.
4. Server dobara chalayein, /docs mein pehle login, phir GET /api/ai/status: available true aana chahiye.
5. POST /api/ai/summarize mein sirf NAKLI test text daalein, consent true.
6. Zaroori: free key par Google content apne products behtar karne ke liye istemal karta hai aur insani
   reviewer parh sakte hain, aur Google khud kehta hai ke hassas ya zaati maloomat free service mein na bhejein.
   Is liye app free key ko sirf APP_ENV=development mein chalne deti hai. Asli users ke liye billing wali
   (paid) key aur AI_TIER=paid chahiye. Redaction name aur pata nahi hatati.
7. AI sirf draft banata hai; user approve karta hai. Bachon ke cases (category children) mein AI band hai.

## Naya (Phase 4) API
GET /api/ai/status, POST /api/ai/clarify, POST /api/ai/summarize;
POST /api/requests mein ab optional ai_used (summary AI draft se shuru hui).

## Phase 5: wakeel ka raasta (ek ek karke)
1. Wakeel ka account: signup karke POST /api/lawyer/apply (bar_council, licence_no, city).
2. Admin (make-admin wala account): GET /api/admin/lawyers?status=pending, phir
   POST /api/admin/lawyers/{id}/verify mein identity_checked true, registration_checked true aur source_note
   (kahan se verify kiya). Jab tak verify nahi, wakeel ko kuch nahi dikhta.
3. User: request banaye aur PUT /api/requests/{id}/consent mein referral true kare.
4. Coordinator/admin: GET /api/coord/lawyers, phir POST /api/coord/requests/{tracking_no}/assign (lawyer_id).
5. Wakeel: GET /api/lawyer/offers (sirf mukhtasar tafseel), POST /api/lawyer/offers/{id}/accept.
   Accept ke baad GET /api/lawyer/cases/{tracking_no} par bayan aur summary nazar aati hai.
6. Revoke: POST /api/coord/assignments/{id}/revoke; wakeel ka access foran band.
Asli wakeel ki verification official Bar Council record se insan hi karega; app sirf record rakhti aur access rokti hai.

## Naya (Phase 5) API
POST /api/lawyer/apply, GET /api/lawyer/me, GET /api/lawyer/offers, POST /api/lawyer/offers/{id}/accept|decline,
GET /api/lawyer/cases, GET /api/lawyer/cases/{tracking_no},
GET /api/admin/lawyers, POST /api/admin/lawyers/{id}/verify|reject|suspend,
GET /api/coord/lawyers, POST /api/coord/requests/{tracking_no}/assign, POST /api/coord/assignments/{id}/revoke

## Phase 6: chat aur files (ek ek karke)
Access: sirf request ka malik (user) ya us ka accepted, verified wakeel. Baqi sab ko 404.
- Chat: POST /api/cases/{tracking_no}/messages (header Idempotency-Key zaroori, body {"body": "..."}),
  GET /api/cases/{tracking_no}/messages. Chat tab khulti hai jab wakeel offer accept kare.
- Files: POST /api/cases/{tracking_no}/attachments (/docs mein "Choose File"), GET .../attachments,
  GET .../attachments/{id} (download), DELETE .../attachments/{id}.
- Wakeel ka access hatne (revoke, ijazat wapas, request band, suspend) par chat aur files foran band;
  user ko apni purani chat aur files hamesha nazar aati hain.
- Files UPLOAD_DIR (default ./uploads) mein random name se rakhi jati hain; asli pehchaan file ke shuru ke
  bytes se hoti hai, name se nahi. Virus scanning abhi nahi hai: public launch se pehle zaroori hai.

## Naya (Phase 6) API
GET/POST /api/cases/{tracking_no}/messages, GET/POST /api/cases/{tracking_no}/attachments,
GET/DELETE /api/cases/{tracking_no}/attachments/{id}

## Phase 7: reminders, reports aur availability (ek ek karke)
- User: PUT /api/me/followup (pref, safe_time "HH:MM", timezone). Channel sirf in_app; email/SMS/WhatsApp
  tab tak nahi jab tak provider configure aur user ki ijazat na ho (422 aata hai, nakli "sent" kabhi nahi).
- Reminder jaldi dekhne ke liye: safe_time "00:00" rakhein, phir admin POST /api/admin/jobs/run chalayein,
  aur GET /api/notifications dekhein. Scheduler khud har SCHEDULER_INTERVAL_SECONDS baad yehi karta hai.
- Daily reminder wakeel se roz jawab ki guarantee nahi; yeh har reminder mein likha hota hai.
- Coordinator: GET /api/coord/reports/daily aur /weekly (sirf ginti aur tracking number).
- Wakeel: POST /api/lawyer/availability (start, end, repeat none/daily/weekly, repeat_count),
  GET /api/lawyer/availability, DELETE /api/lawyer/availability/{id}. Bina timezone ka waqt Asia/Karachi mein.
- User: GET /api/cases/{tracking_no}/slots, POST .../slots/{id}/book, DELETE .../slots/{id}/book
  (sirf apne accepted wakeel ke slot; ek request par ek slot).
- tzdata package Windows par timezone ke liye zaroori hai (pyproject mein pinned).

## Naya (Phase 7) API
GET/PUT /api/me/followup, GET /api/notifications, POST /api/notifications/{id}/read, POST /api/notifications/read-all,
POST /api/admin/jobs/run, GET /api/coord/reports/daily|weekly,
POST/GET /api/lawyer/availability, DELETE /api/lawyer/availability/{id},
GET /api/cases/{tracking_no}/slots, POST|DELETE /api/cases/{tracking_no}/slots/{id}/book

## Phase 8: hifazat (ek ek karke)
- Foran madad: GET /api/emergency (bina login). Verified numbers admin jorta hai (POST /api/admin/contacts mein emergency true).
  Jab tak koi verified number nahi, sirf saaf hidayat aati hai; kuch farzi number kabhi nahi.
- Bachon ka masla: category children par review_status pending; coordinator offer/referral tab tak band; admin
  POST /api/admin/requests/{tracking_no}/child-review (decision cleared, note 10+ harf).
- Password badalna: POST /api/auth/change-password (baqi jagah se logout). Admin CLI:
  uv run python -m app.cli reset-password email  |  revoke-sessions [email]
- Backup: uv run python -m app.cli backup --out backups --keep 7
  Restore (server band karke): uv run python -m app.cli restore backups\FILE.zip --yes
  Backup mein hassas data hai: encrypted jagah rakhein. Abhi sirf SQLite; PostgreSQL ke liye pg_dump.
- Mitana: scheduler band hui requests (RETENTION_DAYS) ka text, chat, files mita deta hai.
  GET /api/me/export, DELETE /api/me (body {"password": "..."}).
- CSRF: doosri website se aayi POST/PUT/DELETE band; proxy ke peeche TRUSTED_ORIGINS mein apna domain likhein.
- docs/INCIDENT_PLAN.md, docs/PRIVACY_AND_RETENTION.md, docs/LAUNCH_READINESS.md (local demo aur public launch alag).

## Naya (Phase 8) API
GET /api/emergency, POST /api/auth/change-password, GET /api/me/export, DELETE /api/me,
POST /api/admin/requests/{tracking_no}/child-review

## Phase 9: RAG (verified qanooni PDF par sawal-jawab)
PDF -> text + (tasveer ho to) OCR -> normalize (LLM ya local) -> tukray -> embedding -> vector store -> similarity search -> jawab, citations ke saath.
Poori tafseel, diagram se code ka naqsha, Tesseract ka install aur hadden: docs/RAG_PIPELINE.md.
API: POST /api/admin/legal-docs, GET /api/admin/legal-docs, DELETE /api/admin/legal-docs/{id}, POST /api/admin/legal-docs/reindex,
GET /api/legal/sources, POST /api/legal/ask. CLI: rag-ingest, rag-ask. Python 3.12 ya 3.13 chahiye (numpy ki wajah se).

## Jo abhi baqi hai (honest list)
- CSRF ka mukammal hal aur rate limit IP ke hisaab se: Phase 8 mein.
- Production (HTTPS, COOKIE_SECURE=true, PostgreSQL): public launch se pehle.
- Password reset aur email verification: agle phase mein.
- Official contacts: abhi sirf 1099 (Ministry of Human Rights) seeded hai, source_url aur verified_on ke saath.
  Launch se pehle har number official source se dobara verify karein; aur contacts verify hone par jorein.
- Pehla admin CLI se banta hai; baad mein admin doosre ko coordinator bana sakta hai.
- Scheduler app ke andar chalta hai (ek process). Kai servers par chalayein to bhi duplicate nahi bante (unique keys), lekin
  asli deployment mein ek alag scheduler process behtar hai.
- Asli Gemini call mere paas chalane ka zariya nahi tha: tests nakli Gemini se chale. Asli call aap ko apni key se check karni hai.
