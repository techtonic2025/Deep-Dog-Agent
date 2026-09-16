# Deep Dog Agent

Deep Dog trasforma una domanda in un report documentato: pianifica la ricerca, consulta il web con agenti specializzati, verifica le fonti e produce un risultato scaricabile in Markdown o PDF.

Questa versione include una semplice interfaccia web locale per Windows. Le chiavi API si inseriscono dal pannello **Setup** e restano soltanto nella memoria del processo: non vengono salvate nel repository o nel browser.

## Funzioni principali

- ricerca multi-agente con fonti e citazioni;
- supporto DeepSeek diretto oppure tramite OpenRouter;
- ricerca con Exa, Tavily o entrambi;
- profilo veloce per le dimostrazioni e profilo approfondito;
- pulsante per interrompere una ricerca in corso;
- esportazione locale in Markdown e PDF impaginato;
- nessun Docker richiesto.

## Requisiti

- Windows 10 o 11;
- Python 3.11 o successivo;
- almeno una chiave per il modello: DeepSeek oppure OpenRouter;
- almeno una chiave di ricerca: Exa oppure Tavily.

Le API esterne sono necessarie per effettuare la ricerca e generare il testo. L'interfaccia, la gestione del report e la creazione del PDF vengono eseguite localmente.

## Installazione

Apri PowerShell nella cartella del progetto ed esegui:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Avvia quindi **Avvia Deep Dog Web.bat**, oppure:

```powershell
.venv\Scripts\python.exe web_app.py
```

Si aprirà `http://127.0.0.1:8765/` nel browser.

## Configurazione

1. Apri **Setup**.
2. Incolla le chiavi che vuoi utilizzare.
3. Scegli provider del modello, motore di ricerca e profondità.
4. Premi **Salva setup**.
5. Scrivi la domanda e premi **Avvia ricerca**.

Durante l'esecuzione puoi premere **Interrompi ricerca**. Alla fine puoi scaricare il report in `.md` oppure in PDF. **Nuova ricerca** pulisce il risultato corrente e prepara una nuova sessione.

In alternativa puoi copiare `.env.example` in `.env` e compilare i valori. Il file `.env` è escluso automaticamente da Git.

## Sicurezza delle chiavi

Non inserire mai chiavi direttamente nel codice. Sono esclusi dal repository:

- `.env` e varianti locali;
- ambienti virtuali `.venv`;
- log, cache e database locali;
- report e PDF generati;
- file temporanei.

Se una chiave è stata pubblicata accidentalmente, revocala dal sito del provider e creane una nuova.

## Licenza e attribuzioni

Il progetto è distribuito con licenza MIT. Conserva [LICENSE](LICENSE), che contiene anche le attribuzioni del progetto originale Deep Dog 2 e di ThinkDepth Deep Research.
