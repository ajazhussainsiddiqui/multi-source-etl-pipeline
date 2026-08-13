from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import sqlite3
import io
import re

app = FastAPI(title="Automation API", description='Verify,alert and save, input csv data file')

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def norm_phone(phone: str) -> str:
    """Same normalization as Task 1."""
    if not phone:
        return ""
    p = re.sub(r"[^0-9]", "", str(phone).strip())
    if p.startswith("91") and len(p) == 12:
        p = p[2:]
    return p if len(p) == 10 else ""

@app.post("/check-duplicates")
async def check_duplicates(request: Request):
    """
    Receives raw CSV text, checks each row against the SQLite DB, returns which ones are duplicates.
    """
    body = await request.body()
    csv_text = body.decode("utf-8")
    
    # Parse CSV
    df = pd.read_csv(io.StringIO(csv_text))
    
    conn = sqlite3.connect("merged.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    duplicates = []
    
    for _, row in df.iterrows():
        email = str(row.get("Email", "")).strip().lower()
        phone_raw = str(row.get("Phone", "")).strip()
        phone = norm_phone(phone_raw)
        name = str(row.get("Full Name", "")).strip()
        
        # Check DB
        cur.execute(
            "SELECT full_name, email, phone FROM persons WHERE LOWER(email) = ? OR phone = ? LIMIT 1",
            (email, phone)
        )
        match = cur.fetchone()
        
        if match:
            duplicates.append({
                "input_name": name,
                "input_email": email,
                "input_phone": phone_raw,
                "matched_name": match["full_name"],
                "matched_email": match["email"],
                "matched_phone": match["phone"]
            })
    
    conn.close()
    
    return {
        "duplicate_count": len(duplicates),
        "duplicates": duplicates,
        "total_checked": len(df)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)