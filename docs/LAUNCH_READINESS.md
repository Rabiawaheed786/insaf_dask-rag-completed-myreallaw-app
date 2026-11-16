# Tayyari ki report: local demo aur public launch alag

## A. Local working demo (aap ki machine par)
Tayyar: signup/login, request aur tracking, no-lawyer fallback, coordinator queue, wakeel ki verification aur offer, chat,
private files, reminders, reports, availability aur booking, optional AI (nakli Gemini se test), backup/restore, mitana, export.
Test: jo `uv run pytest -q` mein pass hue sirf wohi "passed" hain. Frontend abhi nahi: sab kuch `/docs` mein.

## B. Public launch: abhi tayyar NAHI
Jab tak neeche ki cheezein na hon, asli logon ke asli masle na lein.

| Zaroori cheez | Halat |
|---|---|
| Asli frontend (screens, quick exit button, dono zubaanen) | Baqi |
| Pakistani wakeel se Terms, Privacy aur disclaimer ka review | Baqi |
| Asli volunteer wakeel aur unki verification (Bar Council record se) | Baqi |
| Kam az kam 2 coordinators jo roz queue dekhein | Baqi |
| Helpline aur emergency numbers ki official source se verification | Sirf 1099 (MoHR) seeded; emergency list khali |
| Bachon ke cases ka tarbiyat yafta reviewer | Process code mein, asli reviewer baqi |
| HTTPS, domain, `COOKIE_SECURE=true`, PostgreSQL, production server | Baqi |
| Virus scanning files ke liye | Baqi |
| Security review (bahar ke kisi insan se), penetration test | Baqi |
| Backup ka encrypted aur door jagah rakha jana, restore ki mashq | Tools hain, intezam baqi |
| Email/SMS/WhatsApp provider aur user ki ijazat | Jaan boojh kar band |
| Password reset khud-khidmat (email ke zariye) | Abhi sirf admin CLI se |
| Incident ki mashq aur zimmedar log | Plan hai, log baqi |
| Funding: hosting aur AI ka kharch kaun dega | Baqi |
| Gemini ki asli call ka dobara test (paid key, asli data ke liye zaroori) | Baqi |
| RAG: verified qanooni PDF ki library (insani tasdeeq), asli Gemini embeddings par tune | Code hai, library aur tune baqi |

## Aaj ke asli numbers
Pytest ka nateeja README mein likha jata hai; woh sirf is machine/environment ke liye sach hai jahan chala.
