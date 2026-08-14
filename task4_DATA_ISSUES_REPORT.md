# Task 4: Data Issues Report


## The Big Picture

I got three CSVs that look "fine" in Excel. Then I opened them in pandas and everything fell apart. Same people across files with no shared ID, phone numbers in five different formats, CTC values that are either raw rupees or lakhs.

This report is what I found, in the order I found it, and what I did about it.

---

## 1. Phone Numbers: The Format Nightmare

**The pain:** I assumed phone numbers would be clean. They were not.

Source 1 alone had all of these for the same conceptual field:
- with +91 prefix
- leading zero
- clean 10-digit
- with +91 and a dash
- 91 prefix but no +

added `+91-` variants and even had a literal string `"Phone Number"` as a value because of the duplicate header row.

**What I did:** Strip everything that isn't 0-9. If it starts with `91` and is 12 digits total, drop the `91`. If it's 10 digits, keep it. Everything else is invalid. I stored the normalized version as the canonical phone and kept the raw in provenance for audit.

---

## 2. Email Case (S2) 

**The pain:** Source 2 has emails in ALL CAPS. `ISHA.CHOPRA95@MAILTEST.EXAMPLE.ORG`. Source 1 has them in lowercase. `isha.chopra95@mailtest.example.org`. My initial exact-match merge found zero overlaps between S1 and S2 because of this.

**What I did:** `.lower().strip()` on every email before any comparison. Obvious in hindsight, but I spent 20 minutes wondering why only 0 people matched across S1 and S2 before I printed the raw values and facepalmed.

---

## 3. Cities: 16 Ways to Spell the Same Place

**The pain:** Here are the unique city values I extracted from all three files combined:

```
Bangalore, Bengaluru, bangalore, 
GURGAON, Gurugram, gurugram , gurgaon,
Delhi, New Delhi, Delhi NCR, new delhi,
NOIDA, Noida, Noida , 
PUNE, Pune, pune
```

Notice the trailing spaces, used interchangeably, and old-new name issue.

**What I did:** Built a manual mapping dict:
```python
city_map = {
    "bangalore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "gurgaon": "Gurugram",
    "gurugram": "Gurugram",
    "new delhi": "New Delhi",
    "delhi ncr": "New Delhi",
    "noida": "Noida",
    "pune": "Pune",
    "delhi": "Delhi",
}
```

Lowercase --> strip spaces --> map --> title case. I kept `Delhi` separate from `New Delhi` because technically they are different (Delhi is the city, New Delhi is a district within it), but `Delhi NCR` is definitely the metro area so I mapped it to `New Delhi`.

---

## 4. The CTC 

**The pain:** This one genuinely confused me for a while. Source 1 `Current CTC` has values like:
- `4*****` (looks like annual rupees)
- `4.2` (looks like... a mistake?)

I initially thought `4.2` was a corrupted cell or maybe years of experience got mixed in. Then I noticed the pattern: every value below 100 is a clean decimal like other similar numbers. Every value above 100,000 is a large integer. In Indian job portals, CTC is always entered in lakhs (LPA). So `4.2` means INR 4.2 lakhs = INR 4,20,000.

**What I did:** Threshold-based conversion. If CTC < 100, multiply by 1,00,000. If CTC >= 100, keep as-is. This is a heuristic, but it works perfectly on this dataset. I stored the final value as `current_ctc_inr` (integer) so there's no ambiguity.

**Risk:** If someone actually earns INR 99 (impossible) or if a future dataset has monthly CTC in thousands, this breaks.

---

## 5. Rate: /hr vs /month and the "k" Suffix

**The pain:** Source 2 rates look like:
- `1400/hr`
- `15k/month`
- `70k/month`

Some are hourly, some monthly. Some use `k` for thousand. I needed both the numeric value and the unit stored separately so I can compare apples to apples later.

**What I did:** Regex parsing: `([0-9.]+)([k]?)/?(hr|month)`. Extract number, multiply by 1000 if `k` present, normalize unit to `hourly` or `monthly`. Stored as two columns: `rate_value` (float) and `rate_unit` (string).

---

## 6. Dates: Different Formats in One Column

**The pain:** 
- DD-MM-YYYY
- YYYY-MM-DD
- DD-MM-YYYY, leading zero
- human-readable, no leading zero on day
- MM/DD/YYYY — American format!
- another human-readable variant

**What I did:** Tried a cascade of `strptime` formats. The annoying one was `MM/DD/2026` because `07/13/2026` looks like it could be DD/MM/2026 except there is no 13th month. So it's definitely American format. I added `%m/%d/%Y` to the format list. For anything that doesn't match, it returns `None` and I log it.

---

## 7. Status: Case Chaos

**The pain:** Source 2 status values: `Active`, `active`, `ACTIVE`, `paused`, `Inactive`. I need them consistent for filtering.

**What I did:** `.lower()` --> map to title case. `active` --> `Active`, `inactive` --> `Inactive`, `paused` --> `Paused`.

---

## 8. Verified: Six Ways to Say Yes/No

**The pain:** Source 3 `Verified` column has: `Y`, `yes`, `Yes`, `No`, `N`, and literally the string `"Verified"` (from the duplicate header row).

**What I did:** Normalize to boolean. `y/yes/true/1` --> `True`. `n/no/false/0` --> `False`. Everything else (including the header string) → `None`.

---

## 9. Duplicate Header Row in Source 3

**The pain:** Row 14 of `source3_cbnexus_contacts.csv` is:
```
Name,Phone Number,City,Verified,Projects Completed
```

It's the exact column headers repeated as data. If I hadn't checked for this, it would have created a fake person named "Name" with phone "Phone Number" in city "City" (this look real intentional created).

**What I did:** Filtered out any row where `Name.strip().lower() == "name"`. Simple but critical.

---

## 10. Row in Source 2 (Column Shift)

**The pain:** In `source2_gig_workers.csv`:
```
"react, javascript, mysql",ISHA.CHOPRA95@MAILTEST.EXAMPLE.ORG,Isha Chopra,1406/hr,Pune,active
```

The skills string `"react, javascript, mysql"` got quoted and shoved into the `email_id` column. Because of the quote, pandas parsed it as one field, pushing everything else one column to the right. So `email_id` contains skills, `worker_name` contains the email, `rate` contains the name, etc.

**What I did:** After loading, I filtered out any row where the `email_id` field doesn't contain `@`. This catches the shifted row because `"react, javascript, mysql"` has no `@`.

---

## 11. Duplicate Person: Nikhil Chopra (Alt Email)

**The pain:** In Source 1, `Nikhil Chopra` appears twice:
- `alt.nikhil.chopra70@example.com`, phone `9000000103`, CTC `7.8`
- `nikhil.chopra70@example.com`, phone `9000000103`, CTC `7.8`

Same person, same phone, same CTC, different email (one has an `alt.` prefix). My initial unique-email check treated them as different people.

**What I did:** Union-Find clustering by email AND phone. Since both rows share the same normalized phone, they get merged into one cluster. For the final email, I prefer the non-`alt.` version: `nikhil.chopra70@example.com`.

---

## 12. Name: R. Verma vs Rohit Verma

**The pain:** Source 1 rows 23 and 29:
- Row 23: `R. Verma`, email `rohit.verma13@mailtest.example.org`, phone `9000000294`
- Row 29: `Rohit Verma`, email `rohit.verma13@mailtest.example.org`, phone `9000000294`

Identical everything except the name. `R.` is clearly `Rohit`.

**What I did:** Merged by email+phone. For the final name, I prefer the longest non-abbreviated version. If the best name contains a `.` and there are other names available, I pick the one without `.`. Result: `Rohit Verma`.

---

## 13. Same Name, Different People: Arjun Mehta

**The pain:** This almost broke my matching logic. Here is what I found:

The S1 and S3-row-3 Arjun Mehtas share phone `9000000131` same person.  
The S2 Arjun Mehta has a different email and no phone I cannot confidently link him to anyone. He stays as his own cluster (1 source only).  
The S3 Arjun Mehta has phone different from the other two and different project count, different person entirely.

**What I did:** My phone+name matching with last-name sanity check correctly kept the two S3 Arjun Mehtas separate because they have different phones. The S2 Arjun Mehta has no phone and a different email, so he doesn't match anyone by email either. He remains isolated.

---

## 14. Isha Chopra in Source 2: Duplicate

**The pain:** After fixing the column-shifted row 18, I noticed Isha Chopra appears in S2 at row 5 with email `ISHA.CHOPRA95@MAILTEST.EXAMPLE.ORG`. But the malformed row 18 also references the same email (as the `worker_name` column after the shift). The actual Isha Chopra data is fine; the shifted row is garbage.

**What I did:** Dropped the garbage row. The real Isha Chopra (row 5) correctly matches Source 1 and Source 3 by email/phone and becomes a 3-source person.

---

## 15. Trailing Spaces in City Names

**The pain:** `Noida ` (with a space), `gurugram ` (with a space). These look identical to `Noida` and `Gurugram` in a table but fail string equality checks.

**What I did:** `.strip()` on every city before normalization. Also collapsed multiple internal spaces with `re.sub(r"\s+", " ", ...)`.

---

## 16. Source 3 Has No Email

**The pain:** This was the biggest architectural challenge. Source 1 and Source 2 share an email column, so matching them is trivial. Source 3 only has `Name`, `Phone Number`, `City`, `Verified`, `Projects Completed`. No email.

So how do I know if a person in S3 is the same as a person in S1? I have to use phone + name. But phone alone is dangerous (what if two people share a phone? Unlikely but possible). Name alone is dangerous (see Arjun Mehta above).

**What I did:** For S1-->S3 matching, I require **both phone match AND last-name match**. The logic:
1. Normalize phone to 10 digits.
2. If an S1 record and an S3 record share the same normalized phone, check if their last names match.
3. If yes, union them. If no, keep them separate.

For people who only exist in S3 (no matching phone in S1/S2), they stay as single-source records. That's correct — we have no way to link them.

