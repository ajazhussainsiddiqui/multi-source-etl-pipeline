# AI Automation


## File Structure

```
multi-source-etl-pipeline/
├── assets/
│   ├──         # (some aduio smaple to check) 
│   └── screenshot_webhook_site_alert.png
├── audio_uploads/              # Created at runtime by Task 3
├── NISQA/                      # Cloned from gabrielmittag/NISQA for audio quality scoring
├── .gitignore
├── merged.db                   # SQLite DB from Task 1 (created at runtime)
├── n8n_duplicate_alert.json    # Exported n8n workflow (Task 2)
├── requirements.txt
├── source1_naukri_applicants.csv
├── source2_gig_workers.csv
├── source3_cbnexus_contacts.csv
├── task1_merge.py              # Task 1: Merge 3 CSVs into SQLite via SQLAlchemy
├── task2_n8n_automation_api.py # Task 2: FastAPI service for n8n duplicate-check flow
├── task3_audio_app.py          # Task 3: Streamlit audio collection app
├── task4_DATA_ISSUES_REPORT.md # Task 4: Full data quality issues report
└── task5.pdf                   # Task 5: Stretch thinking (one-page pdf)
```

---

## Setup Steps

### Prerequisites

- Python 3.10+
- Node.js + npm (for n8n)
- Docker (optional, for n8n)

### 1. Clone / Download

```bash
cd multi-source-etl-pipeline
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

Contents of `requirements.txt`:
```
numpy==1.26.4
pandas==2.2.1
SQLAlchemy==2.0.43
fastapi==0.129.0
uvicorn==0.41.0
torch==2.2.1+cu118
torchaudio==2.2.1+cu118
torchvision==0.17.1+cu118
nisqa==2.0.post2
soundfile==0.13.1
pyloudnorm==0.2.0
mutagen==1.48.1
streamlit==1.45.1
```

> **Note on NISQA:** The `nisqa` package is not on PyPI. Clone it manually:
> ```bash
> git clone https://github.com/gabrielmittag/NISQA.git
> cd NISQA && pip install -e .
> cd ..
> ```
> The `NISQA/` folder in this repo is that clone.

### 3. Task 1: Run the Merge Pipeline

```bash
python task1_merge.py
```

This creates `merged.db` (SQLite) with two tables:
- `persons`  deduplicated golden records
- `source_provenance`  audit trail linking each person back to original CSV rows

**What it does:**
- Ingests all 3 CSVs
- Normalizes phones, emails, cities, dates, CTC, rates, statuses
- Deduplicates using Union-Find clustering (email + phone + name sanity checks)
- 102 raw records → 60 unique persons (15 present in all 3 sources)

### 4. Task 2: Set Up n8n + FastAPI Automation

#### Step A: Install n8n

```bash
npm install n8n -g
n8n start  # (or `n8n` only)
```

Open `http://localhost:5678` and create a local account.

#### Step B: Start the FastAPI Service

In a **separate terminal**:

```bash
python task2_n8n_automation_api.py
```

This starts on `http://127.0.0.1:8000`.

#### Step C: Import the n8n Workflow

1. In n8n, click **Workflows --> Import from File**
2. Select `n8n_duplicate_alert.json`
3. Open the **Check_Duplicate** node and set up SQLite credentials:
   - **Database Path:** Absolute path to `merged.db` 
4. Open the **Send_Alert** node and paste your webhook.site URL
5. Click **Execute Workflow** (play button)

#### Step D: Test It

```bash
curl -X POST http://localhost:5678/webhook-test/csv-upload \
  -H "Content-Type: text/plain" \
  -d 'Email,Phone,Full Name
  tanvi.gupta31@example.com,9000000254,Tanvi Gupta
  brand.new@example.com,9000009999,Brand New'
```

**Expected result:**

The webhook.site page (where you pasted your unique URL) will show:

```json
{"message":"🚨 DUPLICATE ALERT: Found 1 duplicate(s): Tanvi Gupta"}
```


### 5. Task 3: Run the Audio Collection App

```bash
streamlit run task3_audio_app.py
```

Open `http://localhost:8501`.

**Two pages:**
- **Submit Audio**  Enter name + phone, record in-browser or upload a file
- **Submissions**  Gallery with play button + extracted properties (duration, sample rate, bitrate, loudness, quality score)

Audio files are saved to `audio_uploads/` and records go into `merged.db` (table: `audio_submissions`).

### 6. Task 4: Data Issues Report

See [`task4_DATA_ISSUES_REPORT.md`](task4_DATA_ISSUES_REPORT.md) for the full breakdown of every data quality problem found across the 3 CSVs and how each was handled.


### 7. Task 5: Stretch

See `[task5.pdf](task5.pdf)` for the one-page "what breaks at 5,000 users (workers)" analysis.

---

## Stuck Log

> Here are the 3 places that actually broke me.

### #1. The Dataset Was a Minefield I Didn't See Coming

**What happened:** I opened the CSVs in pandas and they looked fine. Then I started writing the merge logic and everything fell apart. Source 2 had a row where the `email_id` column contained `"react, javascript, mysql"` because of a quote-wrapping issue that shifted every column right by one. Source 3 had a literal duplicate header row (`Name,Phone Number,City...`) sitting in the middle of the data. And the CTC column had values like `4.2` next to `410000`, I genuinely thought `4.2` was a corrupted cell, then I relised it is mean be this.

**What I searched:**
- "pandas csv column shift quoted string"
- "why does pandas parse csv wrong when field contains comma"
- "naukri CTC column what unit"


**What I rejected and why:**
- **Rejected:** Treating `4.2` as an error and dropping those rows. That would have thrown away 21 out of 42 rows. The data is intentionally messy, not broken.
- **Rejected:** Using `pd.to_numeric(errors='coerce')` and imputing missing CTCs. That would mask the real unit confusion. Instead I wrote a threshold-based converter: <100 --> multiply by 1,00,000.

**How I got unstuck:** I stopped trying to "fix" the CSV parser for the shifted row and just validated emails after loading. Any row where `email_id` doesn't contain `@` gets dropped. For the CTC, I accepted the lakhs interpretation and moved on. It took about 2 hours of staring at raw values before I trusted the pattern.

> In this data even my ML data processing skill does't work to fix all the dirty data, I need to learn little extra to complete this task successfully. 

---

### #2. n8n Could Not Talk to My FastAPI Service (IPv4 vs IPv6)

**What happened:** I built the FastAPI service (`task2_n8n_automation_api.py`) and it ran fine on `http://localhost:8000`. I could curl it directly from my terminal and get correct responses. But when n8n's HTTP Request node tried to hit `http://localhost:8000/check-duplicates`, it threw erros every single time. I restarted both services 10 times. I checked ports. I checked firewalls. Nothing worked.

**What I searched:**
- "n8n HTTP Request localhost connection refused"
- "n8n cannot connect to local service"
- "node.js localhost resolves to ipv6"

**What I asked AI:** I described the exact error that include this (`::1`) charector contains errors to gemini: "n8n HTTP Request node gets ECONNREFUSED to localhost:8000 but curl works fine." It immediately asked whether n8n resolves `localhost` to IPv6  while my FastAPI was binding to IPv4 (`127.0.0.1`).

**What I rejected and why:**
- **Rejected:** Switching FastAPI to bind on `0.0.0.0` and using my machine's LAN IP. That would work but it's a hack and breaks if I demo on a different network.
- **Rejected:** Using Docker networking to put both services in the same container network. Overkill for a local demo and would add 30 minutes of Docker config to my video.
- **Rejected:** Changing n8n's Node.js DNS resolution settings. Too deep in the weeds.

**How I got unstuck:** Changed the n8n HTTP Request node URL from `http://localhost:8000/check-duplicates` to `http://127.0.0.1:8000/check-duplicates`. That was it. One line. `localhost` resolves to `::1` (IPv6) in Node.js on my machine, but FastAPI's default Uvicorn bind is IPv4-only (`127.0.0.1`). They were talking past each other. 

---

### #3. Finding the Right Audio Quality Model (NISQA)

**What happened:** Previosilly I worked on TTS/whisper models but never touched audio processing or audio ML before this assignment. The requirements say "automatically extract and store: duration, sample rate, bitrate, and loudness" those are easy, standard libraries handle them. But the bonus asks for "a rough noise/quality estimate." I had no idea where to start. I search about this. I tried `librosa` first for spectral analysis, but that gives you features, not a human-interpretable quality score. I wanted something that outputs a single number like "this audio is 72/100 quality."

**What I searched:**
- "python audio quality assessment library"
- "speech quality estimation MOS score python"
- "PESQ STOI SI-SDR python implementation"
- "NISQA vs PESQ vs POLQA python"
- "github audio quality model pretrained"
- "Huggingface audio models / audio processing model"

**What I asked AI:** I asked (mostilly use google'e buld serach enine gemini model) "what is the state-of-the-art open-source tool for predicting speech quality from a raw audio file?" It suggested many options include NISQA (Neural Inference-based Speech Quality Assessment). I had never heard of it. It's not on PyPI. It's a research repo with 300 stars. I was worried it would be abandonware.

**What I rejected and why:**
- **Rejected:** Using `librosa` + manual spectral features (SNR, harmonic-to-noise ratio) as the primary quality metric. It works but produces numbers that don't correlate well with perceived speech quality. The assignment says "rough noise/quality estimate" but I wanted something defensible, not a hand-rolled heuristic.
- **Rejected:** Using `pesq` PyPI package directly. It only gives PESQ (narrowband) and doesn't handle the full quality pipeline. NISQA gives a MOS score which is the industry standard.
- **Rejected:** Using a cloud API (like Google Speech-to-Text's confidence score as a proxy for quality). The assignment wants local processing, and I didn't want API keys in my submission and find free api provider is own a kind of task.

**How I got unstuck:** I cloned `https://github.com/gabrielmittag/NISQA.git` and tried to run it. It failed with a cascade of errors:
1. Missing `weights/nisqa_mos_only.tar`, had to download the pretrained weights from the repo's releases
2. `torchaudio` backend issues on my machine, had to install `soundfile` explicitly
3. NISQA's API is not a simple function call; it uses a config dict and an internal `predict()` method that mutates state
4. The version mismatched, it was major time consuming, I need to uninstall the `panda`, `numpy` and `torch+cuda` installed packages and need to re-install to fix required match version of it and due to large size (troch+cuda) this take lots of time (network speed also contribute in this dealy downloading).   

I spent about 3 hours going back and forth with AI's, pasting each stack trace, getting a fix, hitting the next error. The final `analyze_audio()` function in `task3_audio_app.py` is the result of that grind. I also wrapped it with `torch.inference_mode()` and cached model loading so it doesn't reload SQUIM and NISQA on every upload, still need to work on this before deployement.

---



