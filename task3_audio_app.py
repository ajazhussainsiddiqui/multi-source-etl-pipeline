"""
Task 3: Mini Audio Collection App 
"""

import re
import sqlite3
from datetime import datetime
from pathlib import Path
import streamlit as st


#  Advanced (Deep Learning) Audio Analysis 
import torch
import torchaudio
import soundfile as sf
import pyloudnorm as pyln
from mutagen import File as MutagenFile
from torchaudio.pipelines import SQUIM_OBJECTIVE
from nisqa.NISQA_model import nisqaModel


@st.cache_resource
def load_squim():
    return SQUIM_OBJECTIVE.get_model()


squim = load_squim()


def analyze_audio(file_path):

    # Metadata
    info = sf.info(file_path)

    # Bitrate
    meta = MutagenFile(file_path)
    bitrate = getattr(meta.info, "bitrate", None) if meta else None

    # Loudness
    audio, rate = sf.read(file_path)
    loudness = pyln.Meter(rate).integrated_loudness(audio)

    # SQUIM
    waveform, sr = torchaudio.load(file_path)

    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    if sr != 16000:
        waveform = torchaudio.functional.resample(
            waveform, sr, 16000
        )

    with torch.inference_mode():
        pesq, stoi, si_sdr = squim(waveform)

    # NISQA — initialize with ACTUAL file
    nisqa = nisqaModel({
        "mode": "predict_file",
        "deg": file_path,
        "output_dir": "",  # this will create a temperary result storage csv file in home directory
        "pretrained_model": "NISQA/weights/nisqa_mos_only.tar",
        "num_workers": 0,
        "bs": 1,
        "ms_channel": None,
    })

    result = nisqa.predict()

    mos = float(result["mos_pred"][0])
    quality_score = max(0, min(100, (mos - 1) / 4 * 100))

    return {
        "duration_sec": round(info.duration, 2),
        "sample_rate_khz": round(info.samplerate / 1000, 2),
        "channels": info.channels,
        "bitrate_kbps": round(bitrate / 1000, 1) if bitrate else None,
        "loudness_lufs": round(loudness, 2),
        "pesq": round(pesq.item(), 2),
        "stoi": round(stoi.item(), 2),
        "si_sdr_db": round(si_sdr.item(), 2),
        "mos": round(mos, 2),
        "quality_score": round(quality_score, 1),
    }


#  Config 
DB_PATH = "merged.db"
AUDIO_DIR = Path("audio_uploads")
AUDIO_DIR.mkdir(exist_ok=True)


#  DB
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audio_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_size_bytes INTEGER,
            duration_sec REAL,
            sample_rate_khz REAL,
            channels INTEGER,
            bitrate_kbps REAL,
            loudness_lufs REAL,
            pesq REAL,
            stoi REAL,
            si_sdr_db REAL,
            mos REAL,
            quality_score REAL,
            submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_submission(name, phone, file_path, file_name, file_size, analysis):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO audio_submissions
        (full_name, phone, file_path, file_name, file_size_bytes,
         duration_sec, sample_rate_khz, channels, bitrate_kbps,
         loudness_lufs, pesq, stoi, si_sdr_db, mos, quality_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name, phone, str(file_path), file_name, file_size,
        analysis["duration_sec"], analysis["sample_rate_khz"],
        analysis["channels"], analysis["bitrate_kbps"],
        analysis["loudness_lufs"], analysis["pesq"], analysis["stoi"],
        analysis["si_sdr_db"], analysis["mos"], analysis["quality_score"],
    ))
    conn.commit()
    conn.close()


def get_all_submissions():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM audio_submissions ORDER BY submitted_at DESC"
    )]
    conn.close()
    return rows


# Streamlit UI
 
def page_submit():
    st.header("🎙️ Submit Audio")

    with st.form("audio_form"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Full Name")
        phone = c2.text_input("Phone Number")

        tab1, tab2 = st.tabs(["🎤 Record", "📁 Upload"])
        with tab1:
            recorded = st.audio_input("Click to record") if hasattr(st, "audio_input") else None
            if not hasattr(st, "audio_input"):
                st.info("Recording requires Streamlit ≥ 1.35")
        with tab2:
            uploaded = st.file_uploader("Upload audio", type=["wav", "mp3", "ogg", "m4a", "flac"])

        submitted = st.form_submit_button("🚀 Submit [Analysis]", use_container_width=True)

    if not submitted:
        return

    # Pick audio source
    audio_bytes = None
    source_name = ""
    if recorded is not None:
        audio_bytes = recorded.getvalue()
        source_name = "recorded.wav"
    elif uploaded is not None:
        audio_bytes = uploaded.getvalue()
        source_name = uploaded.name
    else:
        st.error("Please record or upload audio.")
        return

    if not name.strip() or not phone.strip():
        st.error("Name and phone are required.")
        return

    # Normalize phone
    phone_norm = re.sub(r"[^0-9]", "", phone.strip())
    if phone_norm.startswith("91") and len(phone_norm) == 12:
        phone_norm = phone_norm[2:]
    if len(phone_norm) != 10:
        st.error("Enter a valid 10-digit phone number.")
        return

    # Save file
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r"[^a-zA-Z0-9]", "_", name.strip())
    ext = Path(source_name).suffix or ".wav"
    fname = f"{safe}_{ts}{ext}"
    fpath = AUDIO_DIR / fname

    with open(fpath, "wb") as f:
        f.write(audio_bytes)

    # Analyze
    with st.spinner("Analyzing audio..."):
        analysis = analyze_audio(str(fpath))

    save_submission(name.strip(), phone_norm, fpath, fname, len(audio_bytes), analysis)

    # Show results
    st.success("✅ Submitted!")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Duration", f"{analysis['duration_sec']}s")
    m2.metric("Sample Rate", f"{analysis['sample_rate_khz']} kHz")
    m3.metric("Bitrate", f"{analysis['bitrate_kbps']} kbps" if analysis['bitrate_kbps'] else "N/A")
    m4.metric("Loudness", f"{analysis['loudness_lufs']} LUFS")
    st.metric("Quality Score", f"{analysis['quality_score']}/100")
    with st.expander("🔬 Details"):
        st.json({k: v for k, v in analysis.items() if k not in ("duration_sec", "sample_rate_khz", "channels", "bitrate_kbps", "loudness_lufs", "quality_score")})


def page_gallery():
    st.header("📋 Submissions")
    rows = get_all_submissions()
    if not rows:
        st.info("No submissions yet.")
        return

    st.write(f"**{len(rows)}** submission(s)")
    for r in rows:
        with st.container(border=True):
            a, b, c = st.columns([2, 3, 2])
            with a:
                st.markdown(f"**{r['full_name']}**")
                st.caption(f"📞 {r['phone']}  •  🕐 {r['submitted_at']}")
            with b:
                fp = Path(r["file_path"])
                if fp.exists():
                    st.audio(str(fp))
                else:
                    st.error("File missing")
            with c:
                st.markdown("**Properties**")
                st.write(f"⏱ Duration: {r['duration_sec']}s  |  🔊 {r['sample_rate_khz']} kHz")
                st.write(f"🔊 Sample Rate: {r['sample_rate_khz']} kHz")
                st.write(f"📊 Bitrate: {r['bitrate_kbps']} kbps" if r['bitrate_kbps'] else "📊 Bitrate: N/A")
                st.write(f"🔉 Loudness: {r['loudness_lufs']} LUFS")
                st.write(f"⭐ Quality: {r['quality_score']}/100")
                st.caption(f"PESQ: {r['pesq']}  STOI: {r['stoi']}  SI-SDR: {r['si_sdr_db']} dB  MOS: {r['mos']}")


# ── Main ──
st.set_page_config(page_title="Audio breakdown info", page_icon="🎙️", layout="wide")
init_db()

st.sidebar.title("Pages")
page = st.sidebar.radio("Navigate", ["🎙️ Submit Audio", "📋 Submissions"])

if page == "🎙️ Submit Audio":
    page_submit()
else:
    page_gallery()