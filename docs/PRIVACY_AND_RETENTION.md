# Privacy aur retention (mitana)

## Hum kya jama karte hain
Email, password (sirf hash), display name, zaban, timezone; request: category, shehar, bayan, summary, safe time;
chat, files, notifications, audit log. CNIC aur ghar ka pata nahi maangte.

## Kabhi nahi
Data bechna, ads, public feed, localStorage mein hassas cheez, logs mein bayan ya message ka matn.

## Kitni der rakhte hain
| Cheez | Kitni der | Kaise |
|---|---|---|
| Band hui request ka bayan, summary, chat, files | `RETENTION_DAYS` (default 365) din band hone ke baad | Khud mit jata hai (scheduler); tracking number, category, shehar ginti ke liye baqi |
| Khuli request | Jab tak user band na kare | User kabhi bhi band kar sakta hai |
| Purani login sessions | Khatam hone par | Khud |
| Audit log | Abhi hamesha (hifazat ke liye) | Launch se pehle muddat tay karein (qanooni mashwara) |
| Backup | Aap tay karein (`backup --keep N`) | Backup mein purana data hota hai: unhein bhi muddat se mitayein |

## User ke huqooq (app mein maujood)
- Apna data dekhna/download: `GET /api/me/export`.
- Apna account mitana: `DELETE /api/me` (password ke saath). Request ka text, chat, files, notifications mit jate hain; wakeel ka access foran band.
- Referral ki ijazat kabhi bhi wapas: wakeel ka access foran band.

## Jo abhi nahi hai (sach)
- Backup ke andar ka purana data mitana: backup se restore karne par purana data wapas aa sakta hai. Isliye backup ki muddat chhoti rakhein.
- Wakeel/coordinator/admin ka account khud mitana (admin ke zariye hota hai).
- Audit log ki retention aur qanooni muddat. Pakistan ke privacy qawaneen ke mutabiq final tay karwayein.
