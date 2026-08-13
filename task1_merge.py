#!/usr/bin/env python3
"""
Task 1 - Merge (core)

Merges 3 messy CSV sources into a single SQLite database using SQLAlchemy.
Same person across multiple files becomes ONE record.
"""

import re
import pandas as pd
from datetime import datetime
from collections import defaultdict, Counter
from typing import Optional, List, Dict, Tuple

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, 
    Boolean, Date, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship, Session
from sqlalchemy.sql import func



# CONFIG

DB_PATH = "merged.db"
SOURCE1 = "source1_naukri_applicants.csv"
SOURCE2 = "source2_gig_workers.csv"
SOURCE3 = "source3_cbnexus_contacts.csv"



# SQLALCHEMY MODELS

Base = declarative_base()

class Person(Base):
    __tablename__ = "persons"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(200), nullable=False)
    email = Column(String(200), nullable=True, index=True)
    phone = Column(String(20), nullable=True, index=True)
    city = Column(String(100), nullable=True)
    
    experience_years = Column(Float, nullable=True)
    current_ctc_inr = Column(Integer, nullable=True)
    applied_date = Column(Date, nullable=True)
    skills = Column(Text, nullable=True)
    
    rate_value = Column(Float, nullable=True)
    rate_unit = Column(String(20), nullable=True)
    worker_status = Column(String(50), nullable=True)
    verified = Column(Boolean, nullable=True)
    projects_completed = Column(Integer, nullable=True)
    
    source1_present = Column(Boolean, default=False)
    source2_present = Column(Boolean, default=False)
    source3_present = Column(Boolean, default=False)
    num_sources = Column(Integer, default=0)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    provenance = relationship(
        "SourceProvenance", 
        back_populates="person", 
        cascade="all, delete-orphan"
    )


class SourceProvenance(Base):
    __tablename__ = "source_provenance"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("persons.id"), nullable=False)
    source_name = Column(String(50), nullable=False)
    source_row_index = Column(Integer, nullable=True)
    raw_data_json = Column(Text, nullable=True)
    
    person = relationship("Person", back_populates="provenance")



# NORMALIZATION HELPERS


def norm_email(email: str) -> Optional[str]:
    if pd.isna(email) or str(email).strip() == "":
        return None
    e = str(email).strip().lower()
    if "@" not in e or "." not in e.split("@")[-1]:
        return None
    return e


def norm_phone(phone) -> Optional[str]:
    if pd.isna(phone) or str(phone).strip().lower() in ["", "phone number"]:
        return None
    p = re.sub(r"[^0-9]", "", str(phone).strip())
    if p.startswith("91") and len(p) == 12:
        p = p[2:]
    return p if len(p) == 10 else None


def norm_name(name: str) -> str:
    if pd.isna(name) or str(name).strip().lower() in ["", "name"]:
        return ""
    return str(name).strip().title()


def norm_city(city: str) -> str:
    if pd.isna(city) or str(city).strip().lower() in ["", "city"]:
        return ""
    c = re.sub(r"\s+", " ", str(city).strip().lower()).strip()
    city_map = {
        "bangalore": "Bengaluru",
        "bengaluru": "Bengaluru",
        "gurgaon": "Gurugram",
        "gurugram": "Gurugram",
        "new delhi": "New Delhi",
        "delhi ncr": "New Delhi",
        "delhi": "Delhi",
        "noida": "Noida",
        "pune": "Pune",
    }
    return city_map.get(c, c.title())


def parse_date(date_str: str) -> Optional[datetime]:
    if pd.isna(date_str) or str(date_str).strip() == "":
        return None
    d = str(date_str).strip()
    formats = [
        "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%m/%d/%Y",
        "%d-%m-%y", "%d %B %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(d, fmt)
        except ValueError:
            continue
    return None


def parse_ctc(ctc_val) -> Optional[int]:
    """Convert CTC to annual INR. Handles raw rupees and lakhs."""
    if pd.isna(ctc_val):
        return None
    try:
        val = float(ctc_val)
    except (ValueError, TypeError):
        return None
    # Small decimals like 4.2, 8.3 are lakhs; large numbers are raw rupees
    return int(val * 100000) if val < 100 else int(val)


def parse_rate(rate_str: str) -> Tuple[Optional[float], Optional[str]]:
    if pd.isna(rate_str) or str(rate_str).strip() == "":
        return None, None
    r = str(rate_str).strip().lower()
    match = re.match(r"([0-9.]+)([k]?)/*(?:hr|hour|month|mon)", r)
    if not match:
        return None, None
    num_str, k = match.group(1), match.group(2)
    try:
        num = float(num_str)
    except ValueError:
        return None, None
    if k:
        num *= 1000
    unit = "hourly" if "hr" in r or "hour" in r else "monthly"
    return num, unit


def norm_skills(skills_str: str) -> List[str]:
    if pd.isna(skills_str) or str(skills_str).strip() == "":
        return []
    skills = [s.strip().title() for s in str(skills_str).split(",")]
    return list(dict.fromkeys(skills))


def norm_verified(v) -> Optional[bool]:
    if pd.isna(v):
        return None
    v_str = str(v).strip().lower()
    if v_str in ("y", "yes", "true", "1"):
        return True
    elif v_str in ("n", "no", "false", "0"):
        return False
    return None


def norm_status(s) -> Optional[str]:
    if pd.isna(s):
        return None
    s_str = str(s).strip().lower()
    mapping = {"active": "Active", "inactive": "Inactive", "paused": "Paused"}
    return mapping.get(s_str, s_str.title())



# UNION-FIND FOR DEDUPLICATION


class UnionFind:
    def __init__(self):
        self.parent = {}
        self.rank = {}
    
    def find(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self.rank[x] = 0
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    
    def union(self, x, y):
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1



# MERGE LOGIC


def merge_cluster(members: List[Dict]) -> Dict:
    emails, phones, cities, skills = set(), set(), set(), set()
    names = []
    experience = ctc = applied_date = rate_val = rate_unit = status = None
    verified = None
    projects_completed = None
    sources_present = set()
    
    for m in members:
        row = m["raw"]
        sources_present.add(m["source"])
        
        if m["email"]:
            emails.add(m["email"])
        if m["phone"]:
            phones.add(m["phone"])
        if m["name"]:
            names.append(m["name"])
        
        city = row.get("norm_city", "") if isinstance(row, pd.Series) else ""
        if city:
            cities.add(city)
        
        member_skills = row.get("norm_skills", [])
        if isinstance(member_skills, list):
            skills.update(member_skills)
        
        if m["source"] == "source1":
            if pd.notna(row.get("Experience (Years)")) and experience is None:
                experience = float(row["Experience (Years)"])
            if pd.notna(row.get("parsed_ctc")) and ctc is None:
                ctc = int(row["parsed_ctc"])
            if pd.notna(row.get("parsed_date")) and applied_date is None:
                applied_date = row["parsed_date"]
        
        elif m["source"] == "source2":
            if pd.notna(row.get("parsed_rate")) and rate_val is None:
                rate_val = float(row["parsed_rate"])
                rate_unit = row.get("rate_unit")
            if pd.notna(row.get("norm_status")) and status is None:
                status = row["norm_status"]
        
        elif m["source"] == "source3":
            if pd.notna(row.get("norm_verified")):
                if verified is None or row["norm_verified"]:
                    verified = row["norm_verified"]
            if pd.notna(row.get("projects_completed")):
                pc = int(row["projects_completed"])
                projects_completed = pc if projects_completed is None else max(projects_completed, pc)
    
    # Conflict resolution
    # Name: prefer longest, non-abbreviated
    best_name = ""
    for n in names:
        if len(n) > len(best_name):
            best_name = n
    if "." in best_name and len(names) > 1:
        for n in names:
            if "." not in n:
                best_name = n
                break
    
    # Email: prefer non-alt, longest
    best_email = ""
    for e in emails:
        if "alt." not in e and len(e) > len(best_email):
            best_email = e
    if not best_email and emails:
        best_email = list(emails)[0]
    
    best_phone = list(phones)[0] if phones else ""
    best_city = Counter(cities).most_common(1)[0][0] if cities else ""
    best_skills = ", ".join(sorted(skills))
    
    return {
        "full_name": best_name,
        "email": best_email,
        "phone": best_phone,
        "city": best_city,
        "experience_years": experience,
        "current_ctc_inr": ctc,
        "applied_date": applied_date.date() if applied_date else None,
        "skills": best_skills,
        "rate_value": rate_val,
        "rate_unit": rate_unit,
        "worker_status": status,
        "verified": verified,
        "projects_completed": projects_completed,
        "source1_present": "source1" in sources_present,
        "source2_present": "source2" in sources_present,
        "source3_present": "source3" in sources_present,
        "num_sources": len(sources_present),
    }



# MAIN PIPELINE


def run_pipeline():
    print("=" * 60)
    print("Task 1 - Merge Pipeline")
    print("=" * 60)
    
    # --- Load ---
    print("\n[1/6] Loading raw CSVs...")
    s1_raw = pd.read_csv(SOURCE1)
    s2_raw = pd.read_csv(SOURCE2)
    s3_raw = pd.read_csv(SOURCE3)
    print(f"      S1: {s1_raw.shape[0]} rows | S2: {s2_raw.shape[0]} rows | S3: {s3_raw.shape[0]} rows")
    
    # --- Clean Source 1 ---
    print("\n Cleaning Source 1 (Naukri)...")
    s1 = s1_raw.copy()
    s1["norm_email"] = s1["Email"].apply(norm_email)
    s1["norm_phone"] = s1["Phone"].apply(norm_phone)
    s1["norm_name"] = s1["Full Name"].apply(norm_name)
    s1["norm_city"] = s1["City"].apply(norm_city)
    s1["parsed_ctc"] = s1["Current CTC"].apply(parse_ctc)
    s1["parsed_date"] = s1["Applied Date"].apply(parse_date)
    s1["norm_skills"] = s1["Skills"].apply(norm_skills)
    s1 = s1.dropna(subset=["norm_email", "norm_phone"], how="all")
    print(f"      Clean: {len(s1)} rows")
    
    # --- Clean Source 2 ---
    print("\n Cleaning Source 2 (Gig Workers)...")
    s2 = s2_raw.copy()
    s2 = s2.dropna(subset=["email_id", "worker_name"], how="all")
    s2 = s2[s2["email_id"].apply(lambda x: "@" in str(x) if pd.notna(x) else False)]
    s2["norm_email"] = s2["email_id"].apply(norm_email)
    s2["norm_name"] = s2["worker_name"].apply(norm_name)
    s2["norm_city"] = s2["location"].apply(norm_city)
    s2["parsed_rate"], s2["rate_unit"] = zip(*s2["rate"].apply(parse_rate))
    s2["norm_status"] = s2["status"].apply(norm_status)
    s2["norm_skills"] = s2["skill_tags"].apply(norm_skills)
    s2 = s2.dropna(subset=["norm_email"])
    print(f"      Clean: {len(s2)} rows (dropped empty + malformed rows)")
    
    # --- Clean Source 3 ---
    print("\n Cleaning Source 3 (CBNexus)...")
    s3 = s3_raw.copy()
    s3 = s3[s3["Name"].str.strip().str.lower() != "name"]  # drop duplicate header
    s3["norm_name"] = s3["Name"].apply(norm_name)
    s3["norm_phone"] = s3["Phone Number"].apply(norm_phone)
    s3["norm_city"] = s3["City"].apply(norm_city)
    s3["norm_verified"] = s3["Verified"].apply(norm_verified)
    s3["projects_completed"] = pd.to_numeric(s3["Projects Completed"], errors="coerce")
    s3 = s3.dropna(subset=["norm_phone"])
    print(f"      Clean: {len(s3)} rows (dropped duplicate header row)")
    
    # --- Build matching graph ---
    print("\n Deduplicating with Union-Find...")
    uf = UnionFind()
    records = []
    
    for idx, row in s1.iterrows():
        rec_id = f"S1_{idx}"
        records.append({
            "id": rec_id, "source": "source1",
            "email": row["norm_email"], "phone": row["norm_phone"],
            "name": row["norm_name"], "raw": row
        })
        uf.find(rec_id)
    
    for idx, row in s2.iterrows():
        rec_id = f"S2_{idx}"
        records.append({
            "id": rec_id, "source": "source2",
            "email": row["norm_email"], "phone": None,
            "name": row["norm_name"], "raw": row
        })
        uf.find(rec_id)
    
    for idx, row in s3.iterrows():
        rec_id = f"S3_{idx}"
        records.append({
            "id": rec_id, "source": "source3",
            "email": None, "phone": row["norm_phone"],
            "name": row["norm_name"], "raw": row
        })
        uf.find(rec_id)
    
    # Index and union
    email_to_ids = defaultdict(list)
    phone_to_ids = defaultdict(list)
    name_phone_to_ids = defaultdict(list)
    
    for rec in records:
        if rec["email"]:
            email_to_ids[rec["email"]].append(rec["id"])
        if rec["phone"]:
            phone_to_ids[rec["phone"]].append(rec["id"])
        if rec["name"] and rec["phone"]:
            name_phone_to_ids[(rec["name"].lower(), rec["phone"])].append(rec["id"])
    
    for ids in email_to_ids.values():
        for i in range(1, len(ids)):
            uf.union(ids[0], ids[i])
    
    for ids in name_phone_to_ids.values():
        for i in range(1, len(ids)):
            uf.union(ids[0], ids[i])
    
    # Cross-source phone matching (S1/S2 with S3) with name sanity check
    for phone, ids in phone_to_ids.items():
        s12 = [rid for rid in ids if rid.startswith(("S1_", "S2_"))]
        s3_ids = [rid for rid in ids if rid.startswith("S3_")]
        if s12 and s3_ids:
            for s1_id in s12:
                s1_name = next(r["name"] for r in records if r["id"] == s1_id).lower()
                for s3_id in s3_ids:
                    s3_name = next(r["name"] for r in records if r["id"] == s3_id).lower()
                    s1_parts = s1_name.split()
                    s3_parts = s3_name.split()
                    if s1_parts and s3_parts and s1_parts[-1] == s3_parts[-1]:
                        uf.union(s1_id, s3_id)
    
    # Group clusters
    clusters = defaultdict(list)
    for rec in records:
        clusters[uf.find(rec["id"])].append(rec)
    
    print(f"      {len(records)} raw records → {len(clusters)} unique persons")
    source_dist = Counter(len(m) for m in clusters.values())
    print(f"      Cluster sizes: {dict(source_dist)}")
    
    # --- Merge ---
    print("\n Writing to SQLite via SQLAlchemy...")
    engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    
    with Session(engine) as session:
        for root, members in clusters.items():
            person_data = merge_cluster(members)
            
            person = Person(
                full_name=person_data["full_name"],
                email=person_data["email"] or None,
                phone=person_data["phone"] or None,
                city=person_data["city"] or None,
                experience_years=person_data["experience_years"],
                current_ctc_inr=person_data["current_ctc_inr"],
                applied_date=person_data["applied_date"],
                skills=person_data["skills"] or None,
                rate_value=person_data["rate_value"],
                rate_unit=person_data["rate_unit"],
                worker_status=person_data["worker_status"],
                verified=person_data["verified"],
                projects_completed=person_data["projects_completed"],
                source1_present=person_data["source1_present"],
                source2_present=person_data["source2_present"],
                source3_present=person_data["source3_present"],
                num_sources=person_data["num_sources"],
            )
            session.add(person)
            session.flush()  # get person.id
            
            for m in members:
                raw_dict = m["raw"].to_dict() if isinstance(m["raw"], pd.Series) else {}
                # Convert non-serializable values safely
                for k, v in list(raw_dict.items()):
                    if isinstance(v, (datetime, pd.Timestamp)):
                        raw_dict[k] = v.isoformat()
                    elif isinstance(v, float) and pd.isna(v):
                        raw_dict[k] = None
                    elif isinstance(v, (list, tuple)):
                        raw_dict[k] = list(v)  # keep lists as-is, json.dumps handles them
                
                prov = SourceProvenance(
                    person_id=person.id,
                    source_name=m["source"],
                    source_row_index=int(m["id"].split("_")[1]),
                    raw_data_json=str(raw_dict)
                )
                session.add(prov)
        
        session.commit()
    
    # --- Verification ---
    with Session(engine) as session:
        total = session.query(Person).count()
        s1_only = session.query(Person).filter(
            Person.source1_present == True,
            Person.source2_present == False,
            Person.source3_present == False
        ).count()
        s2_only = session.query(Person).filter(
            Person.source2_present == True,
            Person.source1_present == False,
            Person.source3_present == False
        ).count()
        s3_only = session.query(Person).filter(
            Person.source3_present == True,
            Person.source1_present == False,
            Person.source2_present == False
        ).count()
        all_three = session.query(Person).filter(
            Person.source1_present == True,
            Person.source2_present == True,
            Person.source3_present == True
        ).count()
        
        print(f"\n{'='*60}")
        print("DATABASE SUMMARY")
        print(f"{'='*60}")
        print(f"Total unique persons:     {total}")
        print(f"Present in all 3 sources: {all_three}")
        print(f"Source 1 only:            {s1_only}")
        print(f"Source 2 only:            {s2_only}")
        print(f"Source 3 only:            {s3_only}")
        print(f"\nDatabase file: {DB_PATH}")
        print(f"Tables: persons, source_provenance")
        print("=" * 60)


if __name__ == "__main__":
    run_pipeline()