"""Frontend ke static tests: file serve hoti hai, har zaban mein har lafz hai, har button asli API ko chalata hai,
koi unsafe tareeqa nahi, aur koi jhoota dawa nahi. (Asli browser mein shakal aap ki aankh se dekhni hai.)"""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

STATIC = Path(__file__).resolve().parent.parent / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = {p.name: p.read_text(encoding="utf-8") for p in (STATIC / "js").glob("*.js")}
UR = json.loads((STATIC / "i18n" / "ur.json").read_text(encoding="utf-8"))
EN = json.loads((STATIC / "i18n" / "en.json").read_text(encoding="utf-8"))


def test_index_has_the_safety_controls_and_no_inline_script():
    r = TestClient(app).get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    for needed in ('id="btn-emergency"', 'id="btn-quickexit"', 'id="lang-ur"', 'id="lang-en"', '<main id="main"', 'class="skip"'):
        assert needed in HTML, needed
    assert re.findall(r"<script[^>]*>", HTML) == ['<script type="module" src="/static/js/app.js">']
    assert not re.search(r"\son[a-z]+\s*=", HTML) and ' style="' not in HTML  # CSP ke mutabiq: koi inline handler/style nahi
    assert 'name="viewport"' in HTML and 'lang="ur-Latn"' in HTML


def test_static_files_are_served_and_nothing_else():
    c = TestClient(app)
    for url, kind in (("/static/css/app.css", "text/css"), ("/static/js/app.js", "javascript"),
                      ("/static/js/views.js", "javascript"), ("/static/i18n/ur.json", "json"), ("/static/i18n/en.json", "json")):
        r = c.get(url)
        assert r.status_code == 200 and kind in r.headers["content-type"], url
        assert r.headers["x-content-type-options"] == "nosniff"
    for url in ("/static/nothing.js", "/static/%2e%2e/app/config.py", "/static/../app/config.py", "/static/js/", "/app/config.py", "/.env"):
        assert c.get(url).status_code in (404, 405), url


def test_both_languages_have_the_same_keys_and_no_empty_text():
    assert set(UR) == set(EN)
    assert all(v.strip() for v in UR.values()) and all(v.strip() for v in EN.values())
    banned = "na" + "am"  # user ko yeh Roman Urdu lafz pasand nahi: har jagah English "name"
    assert not any(re.search(rf"\b{banned}\b", v, re.I) for v in list(UR.values()) + list(EN.values()))


def test_every_key_used_in_code_exists_in_both_languages():
    used = set(re.findall(r'data-i18n="([a-z0-9_]+)"', HTML))
    for src in JS.values():
        used |= set(re.findall(r'\bt\("([a-z0-9_]+)"\)', src))
        for pair in re.findall(r't\([a-z]+ \? "([a-z0-9_]+)" : "([a-z0-9_]+)"\)', src):
            used |= set(pair)
    used |= {"role_user", "role_lawyer", "role_coordinator", "role_admin"}  # t("role_" + role)
    assert len(used) > 30
    assert not {k for k in used if k not in UR or k not in EN}


def _norm(path: str) -> str:
    path = re.sub(r"\$\{[^}]+\}", "{}", path.split("?")[0])
    return re.sub(r"\{[^}]*\}", "{}", path)


def test_every_api_call_in_the_frontend_is_a_real_endpoint():
    spec = TestClient(app).get("/openapi.json").json()["paths"]
    known = {_norm(p): set(m) for p, m in spec.items()}
    calls = []
    for src in JS.values():
        calls += re.findall(r'api\("([A-Z]+)",\s*[`"](/api/[^`"]+)[`"]', src)
        for m in re.finditer(r'api\("POST",\s*[a-z]+ \? "(/api/[^"]+)" : "(/api/[^"]+)"', src):
            calls += [("POST", m.group(1)), ("POST", m.group(2))]
        calls += [("UPLOAD", p) for p in re.findall(r'apiUpload\(`(/api/[^`]+)`', src)]
    assert len(calls) >= 40, len(calls)
    for method, path in calls:
        key = _norm(path)
        assert key in known, (method, path)
        assert method == "UPLOAD" and "post" in known[key] or method.lower() in known[key], (method, path)
    # download/href jaise baqi /api/ raaste bhi asli hon
    for src in JS.values():
        for path in re.findall(r'[`"](/api/[^`"]+)[`"]', src):
            assert _norm(path) in known, path
    assert "/static/i18n/" in JS["i18n.js"]


def test_no_unsafe_patterns_and_no_sensitive_browser_storage():
    for name, src in JS.items():
        assert "innerHTML" not in src and "outerHTML" not in src and "insertAdjacentHTML" not in src, name
        assert "eval(" not in src and "document.write" not in src and "sessionStorage" not in src, name
        assert "indexedDB" not in src and "document.cookie" not in src, name
    uses = [(n, m) for n, s in JS.items() for m in re.findall(r"localStorage\.(?:get|set|remove)Item\(([^,)]*)", s)]
    assert uses and all(m.strip() == "KEY" for _, m in uses), uses  # sirf zaban ki pasand
    assert 'const KEY = "lang"' in JS["i18n.js"]


def test_quick_exit_and_emergency_are_wired_and_honest():
    app_js = JS["app.js"]
    assert 'getElementById("btn-quickexit")' in app_js and "location.replace(" in app_js and '"Escape"' in app_js
    assert 'getElementById("btn-emergency")' in app_js and "#/emergency" in app_js
    assert "main.replaceChildren()" in app_js  # screen pehle saaf
    for d in (UR, EN):  # quick exit history nahi mitata: yeh saaf likha ho
        assert "history" in d["quickexit_hint"] and re.search(r"\b(nahi|not)\b", d["quickexit_hint"])
    assert "/api/emergency" in JS["views.js"]


def test_no_unsupported_claims_in_any_text():
    banned = ["100% secure", "100% mehfooz", "insaf guaranteed", "har case free", "every case is free", "guaranteed justice"]
    text = (HTML + " ".join(UR.values()) + " ".join(EN.values())).lower()
    assert not [b for b in banned if b in text]
    assert "guarantee nahi" in UR["footer_honest"] and "does not guarantee" in EN["footer_honest"]
