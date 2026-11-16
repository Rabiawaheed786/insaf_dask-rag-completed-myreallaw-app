# Incident ka plan (data leak ya shak)

Maqsad: nuqsan roknaa, sach batana, aur sabaq lena. Yeh plan kagaz par hai; asli tayyari ke liye is ki mashq (drill) karein.

## 1. Pehchano
Alamaat: ajeeb login, bahut sari ghalat koshishen, audit log mein anjaan `lawyer_viewed` ya `file_downloaded`,
kisi user ki shikayat, server ya backup file ka chori hona, ya key ka public ho jana.
Pehla kaam: waqt aur jo dekha woh likh lein (screenshot mein key ya password na aaye).

## 2. Rokko (pehle 1 ghanta)
1. Sab sessions band: `uv run python -m app.cli revoke-sessions`  (ek user ke liye email likhein).
2. Mutasir wakeel ko suspend: `POST /api/admin/lawyers/{id}/suspend` (is se uske saare cases wapas aur access band).
3. Key/password badlein: AI key (Google AI Studio mein purani delete, nayi banayein), `.env` mein nayi, server dobara.
4. Mutasir user ka password: `uv run python -m app.cli reset-password email`.
5. Agar server/file chori ho: server band karein, backup se saaf jagah restore karein.

## 3. Jaancho
`audit_logs` table dekhein: kis ne kab kya dekha (tracking number ke saath; bayan ya message ka matn kabhi log mein nahi hota).
Sawal: kaun sa data, kitne log, kab se, kaise hua.

## 4. Batao
Mutasir users ko saaf zubaan mein: kya hua, kaun sa data, kya karna hai (password badlein), kis se rabta karna hai.
Jhoot ya "kuch nahi hua" nahi. Agar centre ya wakeel ka data tha to unhein bhi. Qanooni zimmedari ke liye apne qanooni mashir se
poochein ke Pakistan ke qawaneen ke tahat kis ko aur kab batana zaroori hai (yeh tay nahi, main wada nahi karta).

## 5. Theek karo aur seekho
Wajah band karein, test likhein jo dobara na hone de, is document mein sabaq likhein.

## Zimmedar log (launch se pehle bharein)
- Incident lead: ____  | Technical: ____  | Qanooni mashir: ____  | Users se rabta: ____
