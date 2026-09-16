"""Modern local web interface for Deep Dog 2."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

# Windows may choose a legacy charmap encoding when the web server is started
# in the background with redirected logs. Research tools print Unicode status
# markers, so force a safe encoding instead of letting logging abort the tool.
for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from deep_research.integration import (  # noqa: E402
    CancellationToken,
    Credentials,
    RunConfig,
    RuntimeOptions,
    run_research,
    validate_credentials,
)
from pdf_export import report_to_pdf  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
LOCK = threading.Lock()

SUPPORTED_KEYS = (
    "DEEPSEEK_API_KEY",
    "EXA_API_KEY",
    "OPENROUTER_API_KEY",
    "TAVILY_API_KEY",
)


@dataclass
class SetupState:
    keys: dict[str, str] = field(default_factory=dict)
    model_provider: str = "deepseek"
    search_provider: str = "exa"
    speed_profile: str = "fast"


@dataclass
class JobState:
    status: str = "idle"
    message: str = "Pronto per una nuova ricerca"
    prompt: str = ""
    report: str = ""
    error: str = ""
    events: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    cancellation: CancellationToken | None = None


STATE = JobState()
SETUP = SetupState()
EVENT_LABELS = {
    "run_started": "Ricerca avviata",
    "config_validated": "Configurazione verificata",
    "scope_started": "Preparazione del piano di ricerca",
    "scope_completed": "Piano di ricerca completato",
    "draft_started": "Creazione della prima bozza",
    "draft_completed": "Prima bozza completata",
    "supervisor_iteration": "Il supervisore coordina gli agenti",
    "delegation_started": "Ricerca delegata a un agente",
    "subagent_started": "Agente di ricerca avviato",
    "subagent_completed": "Agente di ricerca completato",
    "subagent_failed": "Un agente ha segnalato un errore",
    "source_found": "Nuova fonte trovata",
    "source_read": "Analisi di una fonte",
    "source_saved": "Fonte salvata",
    "report_started": "Scrittura del report finale",
    "citations_validated": "Citazioni verificate",
    "run_completed": "Ricerca completata",
    "run_failed": "Ricerca non riuscita",
}


def app_config(setup: SetupState | None = None) -> RunConfig:
    selected = setup or SETUP
    fast = selected.speed_profile == "fast"
    use_openrouter = selected.model_provider == "openrouter"
    return RunConfig(
        supervisor_model_fallback_chain=["deepseek-flash"],
        subagent_model_fallback_chain=["deepseek-flash"],
        draft_report_model_fallback_chain=["deepseek-flash"],
        disable_model_fallback=True,
        route_via_openrouter=use_openrouter,
        supervisor_route_via_openrouter=use_openrouter,
        subagent_route_via_openrouter=use_openrouter,
        draft_route_via_openrouter=use_openrouter,
        enabled_agents=["ResearchWeb"],
        web_search_engine=selected.search_provider,
        exa_search_type="fast" if fast else "auto",
        exa_search_default_results=5 if fast else 10,
        research_time_min_minutes=0.5 if fast else 2,
        research_time_max_minutes=3 if fast else 10,
        supervisor_max_iterations=7 if fast else 20,
        supervisor_max_concurrent_research=2 if fast else 3,
        supervisor_max_concurrent_discovery=1 if fast else 2,
        subagent_max_iterations=4 if fast else 5,
        subagent_max_searches=2 if fast else 3,
        subagent_max_reads=6 if fast else 10,
        subagent_max_total_reads=12 if fast else 25,
        subagent_max_saves=6 if fast else 10,
        subagent_max_concurrency=3,
        subagent_output_mode="sources",
        discovery_output_mode="report_inline",
        output_mode="none",
        log_mode="none",
        save_report_to_file=False,
        enable_source_log=False,
        logging_enabled=False,
    ).finalize()


def current_setup() -> SetupState:
    with LOCK:
        return SetupState(
            keys=dict(SETUP.keys),
            model_provider=SETUP.model_provider,
            search_provider=SETUP.search_provider,
            speed_profile=SETUP.speed_profile,
        )


def setup_snapshot() -> dict[str, Any]:
    selected = current_setup()
    credentials = Credentials(selected.keys)
    config = app_config(selected)
    check = validate_credentials(config, credentials)
    return {
        "configured": {name: credentials.has(name) for name in SUPPORTED_KEYS},
        "model_provider": selected.model_provider,
        "search_provider": selected.search_provider,
        "speed_profile": selected.speed_profile,
        "ready": check.ok,
        "missing": check.missing_required,
    }


def on_event(event: Any) -> None:
    label = EVENT_LABELS.get(event.type, event.type.replace("_", " ").capitalize())
    with LOCK:
        STATE.message = label
        STATE.events.append(label)
        STATE.events[:] = STATE.events[-80:]


def run_job(prompt: str, cancellation: CancellationToken) -> None:
    selected = current_setup()
    config, credentials = app_config(selected), Credentials(selected.keys)
    check = validate_credentials(config, credentials)
    if not check.ok:
        with LOCK:
            STATE.status = "failed"
            STATE.message = "Configurazione incompleta"
            STATE.error = "Apri Setup e configura: " + ", ".join(check.missing_required)
            STATE.finished_at = time.time()
        return
    try:
        result = asyncio.run(run_research(
            prompt,
            config=config,
            credentials=credentials,
            runtime=RuntimeOptions(
                event_sink=on_event,
                console_enabled=False,
                cancellation=cancellation,
            ),
        ))
        with LOCK:
            STATE.status = result.status
            STATE.report = result.final_report or result.draft_report or ""
            STATE.error = result.failure or ""
            STATE.message = "Report completato" if result.status == "completed" else f"Ricerca terminata: {result.status}"
            STATE.finished_at = time.time()
    except Exception as exc:
        with LOCK:
            STATE.status = "failed"
            STATE.message = "Errore durante la ricerca"
            STATE.error = f"{type(exc).__name__}: {exc}"
            STATE.finished_at = time.time()


def snapshot() -> dict[str, Any]:
    with LOCK:
        elapsed = 0 if STATE.started_at is None else (STATE.finished_at or time.time()) - STATE.started_at
        return {
            "status": STATE.status,
            "message": STATE.message,
            "report": STATE.report,
            "error": STATE.error,
            "events": list(STATE.events),
            "elapsed_seconds": round(elapsed),
        }


HTML = r"""<!doctype html><html lang="it"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Deep Dog</title>
<style>
:root{color-scheme:dark;--bg:#070a0f;--panel:#101620;--muted:#8b98aa;--line:#202a38;--mint:#59f2b0;--danger:#ff7f8d}*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(800px 500px at 8% -8%,#113328 0,transparent 68%),radial-gradient(650px 450px at 95% 8%,#152441 0,transparent 70%),var(--bg);color:#eef5f1;font:16px/1.55 Inter,"Segoe UI",sans-serif}
body:before{content:"";position:fixed;inset:0;pointer-events:none;opacity:.24;background-image:linear-gradient(#ffffff07 1px,transparent 1px),linear-gradient(90deg,#ffffff07 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(#000,transparent 72%)}
main{position:relative;width:min(980px,calc(100% - 30px));margin:auto;padding:30px 0 80px}.hero{display:grid;grid-template-columns:150px 1fr;align-items:center;gap:24px;margin-bottom:20px}.mascot{width:150px;filter:drop-shadow(0 20px 24px #0008)}
.kicker{color:var(--mint);font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase}.hero h1{margin:5px 0 3px;font-size:clamp(42px,8vw,72px);line-height:.95;letter-spacing:-.055em}.hero p{margin:12px 0 0;color:var(--muted);max-width:620px}
.card{background:linear-gradient(145deg,#111722f2,#0c1119f7);border:1px solid var(--line);border-radius:22px;padding:22px;box-shadow:0 26px 80px #0005,inset 0 1px #ffffff09;backdrop-filter:blur(14px)}
textarea,input,select{width:100%;padding:14px 15px;color:#f7fbf8;background:#080c12;border:1px solid #293545;border-radius:13px;font:inherit;outline:none;transition:.2s}textarea{min-height:138px;resize:vertical;padding:17px 18px}textarea:focus,input:focus,select:focus{border-color:var(--mint);box-shadow:0 0 0 4px #59f2b01a}
.actions{display:flex;align-items:center;gap:14px;margin-top:15px;flex-wrap:wrap}button{border:0;border-radius:999px;padding:12px 20px;font:750 15px/1 "Segoe UI";cursor:pointer;transition:.16s}button:hover:not(:disabled){transform:translateY(-1px)}button:disabled{opacity:.45;cursor:not-allowed}#start{background:linear-gradient(100deg,var(--mint),#72ddff);color:#06110c;box-shadow:0 8px 25px #59f2b02b}#stop{display:none;background:#d33d4f;color:#fff;border:1px solid #ff7f8d;box-shadow:0 8px 25px #d33d4f38}#newSearch{display:none;background:#202c3a;color:#eef5f1;border:1px solid #41536a}#download,#downloadPdf{background:#1c2735;color:#eef5f1;border:1px solid #2e3b4b}#downloadPdf{background:linear-gradient(100deg,#16382d,#17384a);border-color:#2f6654}
.setup-toggle{background:#182231;color:#eef5f1;border:1px solid #314052}.setup{margin-bottom:18px}.setup-head{display:flex;align-items:center;gap:12px}.setup-head h2{margin:0;font-size:20px}.setup-head p{margin:2px 0 0;color:var(--muted);font-size:13px}.setup-body{display:none;margin-top:20px;border-top:1px solid var(--line);padding-top:18px}.setup.open .setup-body{display:block}.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.field label{display:block;margin:0 0 6px;color:#cbd7d0;font-size:13px;font-weight:700}.field small{color:var(--muted);font-weight:400}.key-wrap{position:relative}.key-wrap input{padding-right:92px}.key-state{position:absolute;right:12px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:11px}.key-state.ok{color:var(--mint)}.setup-note{color:var(--muted);font-size:12px;margin:14px 0 0}.ready{color:var(--mint);font-size:13px}.not-ready{color:#ffc77d;font-size:13px}
.status{display:flex;gap:10px;align-items:center;color:var(--muted);font-size:14px}.dot{width:9px;height:9px;border-radius:50%;background:#596575}.running .dot{background:var(--mint);animation:pulse 1.5s infinite}.failed .dot{background:var(--danger)}.completed .dot{background:var(--mint)}@keyframes pulse{70%{box-shadow:0 0 0 9px #59f2b000}}
#details{margin-top:18px;color:var(--muted);font-size:13px;max-height:154px;overflow:auto;border-top:1px solid var(--line);padding-top:12px}#details div{padding:3px 0}#error{display:none;margin-top:16px;color:#ffd9dd;background:#32161d;border:1px solid #61303a;border-radius:13px;padding:14px;white-space:pre-wrap}#result{display:none;margin-top:22px}#result h2{margin:0;font-size:24px}#report{white-space:pre-wrap;overflow-wrap:anywhere;margin:0;font:15px/1.72 "Segoe UI";color:#dfe9e3}.meta{margin-left:auto;color:var(--muted);font-size:13px}
@media(max-width:620px){main{padding-top:20px}.hero{grid-template-columns:90px 1fr;gap:12px}.mascot{width:94px}.hero h1{font-size:42px}.hero p{font-size:14px}.card{padding:16px}.meta{margin-left:0}.grid{grid-template-columns:1fr}}
</style></head><body><main>
<header class="hero"><img class="mascot" src="/mascot.png" alt="Cagnolino Deep Dog"><div><div class="kicker">AI research engine</div><h1>Deep Dog</h1><p>Una domanda dentro. Un report documentato fuori. Gli agenti cercano, verificano e sintetizzano per te.</p></div></header>
<section id="setupCard" class="card setup"><div class="setup-head"><div style="flex:1"><h2>Setup</h2><p>Collega modelli e ricerca. Le chiavi restano in memoria solo durante questa sessione.</p></div><span id="setupReady" class="not-ready">Da configurare</span><button id="setupToggle" class="setup-toggle">Configura</button></div>
<div class="setup-body"><div class="grid">
<div class="field"><label for="deepseekKey">DeepSeek API key</label><div class="key-wrap"><input id="deepseekKey" type="password" autocomplete="off" placeholder="sk-…"><span id="deepseekState" class="key-state">non impostata</span></div></div>
<div class="field"><label for="exaKey">Exa API key</label><div class="key-wrap"><input id="exaKey" type="password" autocomplete="off" placeholder="exa-…"><span id="exaState" class="key-state">non impostata</span></div></div>
<div class="field"><label for="openrouterKey">OpenRouter API key <small>(opzionale, anche modelli Anthropic/Google)</small></label><div class="key-wrap"><input id="openrouterKey" type="password" autocomplete="off" placeholder="sk-or-…"><span id="openrouterState" class="key-state">non impostata</span></div></div>
<div class="field"><label for="tavilyKey">Tavily API key <small>(opzionale)</small></label><div class="key-wrap"><input id="tavilyKey" type="password" autocomplete="off" placeholder="tvly-…"><span id="tavilyState" class="key-state">non impostata</span></div></div>
<div class="field"><label for="modelProvider">Modello</label><select id="modelProvider"><option value="deepseek">DeepSeek diretto</option><option value="openrouter">DeepSeek tramite OpenRouter</option></select></div>
<div class="field"><label for="searchProvider">Motore di ricerca</label><select id="searchProvider"><option value="exa">Exa</option><option value="tavily">Tavily</option><option value="both">Exa + Tavily</option></select></div>
<div class="field"><label for="speedProfile">Profondità</label><select id="speedProfile"><option value="fast">Demo veloce · circa 3–5 min</option><option value="deep">Approfondita · fino a 10+ min</option></select></div>
</div><div class="actions"><button id="saveSetup">Salva setup</button><span id="setupMessage" class="meta"></span></div><p class="setup-note">I campi vuoti mantengono le chiavi già caricate dal file .env o inserite in questa sessione. Deep Dog non mostra mai una chiave salvata.</p></div></section>
<section class="card"><textarea id="prompt" placeholder="Es. Qual è il miglior modello AI per programmare considerando qualità e prezzo?"></textarea><div class="actions"><button id="start">Avvia ricerca</button><button id="stop">■ Interrompi ricerca</button><button id="newSearch">＋ Nuova ricerca</button><div id="status" class="status"><span class="dot"></span><span id="statusText">Pronto</span></div><span id="elapsed" class="meta"></span></div><div id="error"></div><div id="details"></div></section>
<section id="result" class="card"><div class="actions" style="margin:0 0 18px"><h2>Report</h2><span style="flex:1"></span><button id="download">Scarica .md</button><button id="downloadPdf">Scarica PDF</button></div><div id="report"></div></section>
</main><script>
const $=id=>document.getElementById(id);let timer;const fmt=n=>{const m=Math.floor(n/60),s=n%60;return m?`${m}m ${s}s`:`${s}s`};
const keyFields={DEEPSEEK_API_KEY:['deepseekKey','deepseekState'],EXA_API_KEY:['exaKey','exaState'],OPENROUTER_API_KEY:['openrouterKey','openrouterState'],TAVILY_API_KEY:['tavilyKey','tavilyState']};
function paintSetup(s){for(const [name,ids] of Object.entries(keyFields)){const el=$(ids[1]),ok=!!s.configured[name];el.textContent=ok?'configurata':'non impostata';el.className='key-state'+(ok?' ok':'')} $('modelProvider').value=s.model_provider;$('searchProvider').value=s.search_provider;$('speedProfile').value=s.speed_profile;$('setupReady').textContent=s.ready?'Pronto':'Da configurare';$('setupReady').className=s.ready?'ready':'not-ready'}
async function loadSetup(){paintSetup(await fetch('/api/setup').then(r=>r.json()))}
$('setupToggle').onclick=()=>{$('setupCard').classList.toggle('open');$('setupToggle').textContent=$('setupCard').classList.contains('open')?'Chiudi':'Configura'};
$('saveSetup').onclick=async()=>{const keys={};for(const [name,ids] of Object.entries(keyFields)){const value=$(ids[0]).value.trim();if(value)keys[name]=value}const r=await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keys,model_provider:$('modelProvider').value,search_provider:$('searchProvider').value,speed_profile:$('speedProfile').value})});const b=await r.json();if(!r.ok){$('setupMessage').textContent=b.error;return}for(const ids of Object.values(keyFields))$(ids[0]).value='';paintSetup(b);$('setupMessage').textContent=b.ready?'Configurazione pronta':'Mancano: '+b.missing.join(', ')};
async function refresh(){const s=await fetch('/api/status').then(r=>r.json());const running=s.status==='running';$('status').className='status '+s.status;$('statusText').textContent=s.message;$('elapsed').textContent=s.status==='idle'?'':fmt(s.elapsed_seconds);$('start').disabled=running;$('stop').style.display=running?'inline-block':'none';$('stop').disabled=s.message==='Interruzione richiesta';$('newSearch').style.display=!running&&(s.report||s.error||s.status!=='idle')?'inline-block':'none';$('error').style.display=s.error?'block':'none';$('error').textContent=s.error;$('details').replaceChildren(...s.events.slice(-12).reverse().map(e=>{const d=document.createElement('div');d.textContent='• '+e;return d}));$('result').style.display=s.report?'block':'none';$('report').textContent=s.report||'';if(running&&!timer)timer=setInterval(refresh,1000);if(!running&&timer){clearInterval(timer);timer=null}}
$('start').onclick=async()=>{const prompt=$('prompt').value.trim();if(!prompt){$('prompt').focus();return}$('result').style.display='none';$('report').textContent='';const r=await fetch('/api/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prompt})});const b=await r.json();if(!r.ok){$('error').style.display='block';$('error').textContent=b.error;return}await refresh()};$('stop').onclick=async()=>{await fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});await refresh()};$('newSearch').onclick=async()=>{const r=await fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(r.ok){$('prompt').value='';await refresh();$('prompt').focus()}};$('download').onclick=()=>location.href='/api/download';$('downloadPdf').onclick=()=>location.href='/api/download-pdf';loadSetup();refresh();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send_bytes(self, data: bytes, content_type: str, status: int = 200, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        self.send_bytes(json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self.send_bytes(HTML.encode(), "text/html; charset=utf-8")
        elif path == "/mascot.png":
            self.send_bytes((ROOT / "assets" / "web" / "deep-dog-mascot.png").read_bytes(), "image/png")
        elif path == "/api/status":
            self.send_json(snapshot())
        elif path == "/api/setup":
            self.send_json(setup_snapshot())
        elif path == "/api/download":
            with LOCK:
                report = STATE.report
            if report:
                self.send_bytes(report.encode(), "text/markdown; charset=utf-8", Content_Disposition='attachment; filename="deep-dog-report.md"')
            else:
                self.send_json({"error": "Nessun report disponibile"}, HTTPStatus.NOT_FOUND)
        elif path == "/api/download-pdf":
            with LOCK:
                report, prompt = STATE.report, STATE.prompt
            if report:
                try:
                    pdf = report_to_pdf(
                        report,
                        prompt,
                        ROOT / "assets" / "web" / "deep-dog-mascot.png",
                    )
                    self.send_bytes(
                        pdf,
                        "application/pdf",
                        Content_Disposition='attachment; filename="deep-dog-report.pdf"',
                    )
                except Exception as exc:
                    self.send_json({"error": f"Creazione PDF non riuscita: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            else:
                self.send_json({"error": "Nessun report disponibile"}, HTTPStatus.NOT_FOUND)
        else:
            self.send_json({"error": "Risorsa non trovata"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/api/start", "/api/setup", "/api/cancel", "/api/reset"):
            self.send_json({"error": "Risorsa non trovata"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 32_000:
                raise ValueError("Richiesta troppo lunga")
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if path == "/api/cancel":
            with LOCK:
                if STATE.status != "running" or STATE.cancellation is None:
                    self.send_json({"error": "Nessuna ricerca in corso"}, HTTPStatus.CONFLICT)
                    return
                STATE.cancellation.cancel("Interrotta dall'utente")
                STATE.message = "Interruzione richiesta"
                STATE.events.append("Interruzione richiesta dall'utente")
            self.send_json({"ok": True}, HTTPStatus.ACCEPTED)
            return
        if path == "/api/reset":
            with LOCK:
                if STATE.status == "running":
                    self.send_json({"error": "Interrompi prima la ricerca in corso"}, HTTPStatus.CONFLICT)
                    return
                STATE.status, STATE.message, STATE.prompt = "idle", "Pronto per una nuova ricerca", ""
                STATE.report, STATE.error, STATE.events = "", "", []
                STATE.started_at, STATE.finished_at, STATE.cancellation = None, None, None
            self.send_json({"ok": True})
            return
        if path == "/api/setup":
            keys = payload.get("keys", {})
            model_provider = str(payload.get("model_provider", "deepseek"))
            search_provider = str(payload.get("search_provider", "exa"))
            speed_profile = str(payload.get("speed_profile", "fast"))
            if not isinstance(keys, dict):
                self.send_json({"error": "Formato chiavi non valido"}, HTTPStatus.BAD_REQUEST)
                return
            if model_provider not in ("deepseek", "openrouter") or search_provider not in ("exa", "tavily", "both") or speed_profile not in ("fast", "deep"):
                self.send_json({"error": "Opzione di setup non valida"}, HTTPStatus.BAD_REQUEST)
                return
            clean_keys = {
                name: str(value).strip()
                for name, value in keys.items()
                if name in SUPPORTED_KEYS and str(value).strip()
            }
            with LOCK:
                if STATE.status == "running":
                    self.send_json({"error": "Attendi la fine della ricerca prima di cambiare setup"}, HTTPStatus.CONFLICT)
                    return
                SETUP.keys.update(clean_keys)
                SETUP.model_provider = model_provider
                SETUP.search_provider = search_provider
                SETUP.speed_profile = speed_profile
            self.send_json(setup_snapshot())
            return
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            self.send_json({"error": "Inserisci una domanda"}, HTTPStatus.BAD_REQUEST)
            return
        with LOCK:
            if STATE.status == "running":
                self.send_json({"error": "Una ricerca è già in corso"}, HTTPStatus.CONFLICT)
                return
            STATE.status, STATE.message, STATE.prompt = "running", "Avvio della ricerca", prompt
            STATE.report, STATE.error, STATE.events = "", "", []
            STATE.started_at, STATE.finished_at = time.time(), None
            STATE.cancellation = CancellationToken()
            cancellation = STATE.cancellation
        threading.Thread(target=run_job, args=(prompt, cancellation), daemon=True).start()
        self.send_json({"ok": True}, HTTPStatus.ACCEPTED)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Deep Dog Web è disponibile su {url}")
    print("Premi Ctrl+C per arrestare il server.")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer arrestato.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
