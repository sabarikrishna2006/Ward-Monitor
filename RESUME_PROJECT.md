# Foqal CareOS — Resume Content

---

## PROJECT HEADER (pick one)

**Option A — product-first**
> **Foqal CareOS — Clinical AI Platform** | *Sole developer, Discharge Summary AI & Cost ML*
> FastAPI · PostgreSQL (Cloud SQL) · XGBoost · Google Gemini · BigQuery · Qdrant · Vite

**Option B — impact-first**
> **Foqal CareOS — AI Discharge Summary & Cost Prediction System for Hospitals**
> Production platform on real MIMIC-IV clinical data · 43K LOC · Python/FastAPI, PostgreSQL, XGBoost, LLM pipeline

---

## FULL BULLETS (6 — use for a project-heavy resume)

- Built and deployed a production clinical AI platform (~43K LOC) on **FastAPI + Google Cloud SQL (PostgreSQL)** with 26 normalized tables, 27 versioned migrations, automated **BigQuery ETL** ingesting real **MIMIC-IV** EHR data, and 8-tier role-based access control with bcrypt auth.

- Designed a **3-pass LLM pipeline** that generates a 15-section NABH-compliant discharge summary: **Pass 1** extracts structured clinical facts (notes, labs, vitals, procedures, meds) into strict JSON; **Pass 2** streams section-wise generation; **Pass 3** independently audits each section against *only* its own authorized source fields — enforcing *generation sources ≡ verification sources* so the auditor cannot rubber-stamp its own context.

- Engineered a **tiered clinical safety gate** (T1 formatting / T2 medication error / T3 critical) that detects hallucinated lab and vital values, wrong drug/dose/frequency, contradicted diagnoses and missed allergies — and **hard-blocks doctor sign-off until every T3 flag is resolved**, backed by digital signature capture (MCI no., designation, signature image), version history, amendment trail and full audit logging.

- Trained and shipped an **XGBoost quantile regression model (P10/P50/P90)** predicting *remaining* hospital cost day-by-day, on **7,077 real admissions / 46,145 day-wise rows / 63 engineered features**; reframed the prediction target from total bill to remaining cost, **eliminating a 32.4% floor-violation rate** where predicted minimums fell below money already billed.

- Improved Day-0 cost accuracy from **103.5% → 88.4% MAPE** by engineering a **shrinkage-based diagnosis cost-band feature** that buckets all 1,317 diagnoses by cost rather than frequency — replacing an "Other" catch-all that gave the model zero signal on 1,302 rare diagnoses; tuned the shrinkage constant (k=10 → k=3) after it over-collapsed band separation, and validated with held-out train/test split and leakage review.

- Served the model live behind FastAPI with a real-time feature builder reading from Cloud SQL, wired into the billing app's multi-stage cost-estimate workflow — **replacing a flat-rate PM-JAY package pricing system** — and built the full clinician-facing surface in vanilla JS/Vite: doctor queue, patient dashboard, section-by-section AI review editor with inline flag resolution, sign-off, signed view, amendment flow, plus billing, CMO and admin dashboards.

---

## COMPACT BULLETS (3 — use if you have limited space)

- Built a production clinical AI platform (FastAPI, PostgreSQL/Cloud SQL, BigQuery, ~43K LOC) that auto-generates 15-section hospital discharge summaries from real MIMIC-IV EHR data via a **3-pass LLM pipeline** — extract → generate → per-section independent verification.

- Designed a **tiered hallucination-detection layer** (T1/T2/T3) that flags fabricated labs, wrong drug doses and missed allergies, and **blocks doctor sign-off until all critical flags are resolved** — with digital signatures, versioning and audit trail for clinical accountability.

- Trained an **XGBoost quantile model (P10/P50/P90)** on 7,077 admissions / 46,145 day-wise rows predicting remaining hospital cost; improved Day-0 MAPE **103.5% → 88.4%** with a shrinkage-based diagnosis cost-band feature, and deployed it live into the billing workflow.

---

## ONE-LINER (LinkedIn headline / portfolio subtitle)

> Clinical AI platform that generates verified hospital discharge summaries via a 3-pass LLM pipeline with tiered hallucination detection, and predicts day-wise patient cost using XGBoost quantile regression — live on real MIMIC-IV data.

---

## SKILLS THIS PROJECT LETS YOU CLAIM

**ML/AI:** XGBoost, quantile regression, feature engineering, shrinkage/regularization, MAPE/MAE evaluation, train-test split & leakage validation, LLM prompt engineering, multi-pass LLM pipelines, RAG (MedCPT embeddings + Qdrant), hallucination detection
**Backend:** Python, FastAPI, async APIs, PostgreSQL, schema migrations, RBAC, bcrypt, streaming responses, background tasks
**Data:** Google BigQuery, MIMIC-IV EHR, ETL pipelines, cache-aside patterns
**Frontend:** JavaScript, Vite, component-driven vanilla JS, multi-role dashboards
**Cloud/DevOps:** Google Cloud SQL, service accounts, nginx, deployment scripting

---

## INTERVIEW TALKING POINTS (know these cold)

**"Walk me through the 3-pass pipeline."**
Pass 1 turns messy EHR rows into a structured clinical JSON — one LLM call, cached per admission so regeneration is fast. Pass 2 generates the 15 sections, streamed. Pass 3 is the interesting one: instead of showing the auditor the whole summary and whole record, each section is verified against *only* the source fields it was allowed to use — e.g. the Discharge Medications section is checked against the medications list, nothing else. That isolation is what makes "this lab value isn't in the source" a reliable signal instead of the model just agreeing with itself.

**"Why quantiles instead of a point estimate?"**
A hospital bill estimate needs a floor and a ceiling, not a single number — P10/P50/P90 gives the patient a range. And the floor has a hard constraint: it can never be below what's already been billed. That's exactly why I changed the target from *total* cost to *remaining* cost — predicting total meant 32.4% of cases produced a floor below money already spent, which is worse than useless to a billing desk.

**"What was the hardest ML decision?"**
The diagnosis cost-band feature. 1,317 diagnoses, but only ~15 got their own one-hot feature and the other 1,302 fell into "Other" — no signal. Bucketing by cost fixes that, but 54% of diagnoses have only *one* admission behind their average, so the raw average is noise. I used shrinkage toward the population mean. First tried k=10, which over-shrunk — the Mid-Low band collapsed to a ₹6,000-wide range, destroying the separation the feature existed to create. Tuned to k=3. Sanity-checked it against the single most expensive diagnosis in the cohort (n=1, ₹31.7L bill) — it shrinks hard but still correctly lands in the High band.

**"How do you know the accuracy gain is real?"**
Held-out train/test split by admission ID (not row — same admission can't straddle the split), evaluated MAPE per hospital day, and a deliberate leakage check: I moved this feature to *diagnosis* rather than *procedures* precisely because procedures can occur on any day of the stay, so a Day-0 model using them would be leaking future information. Diagnosis is legitimately known at admission.

---

## DO NOT CLAIM

- ❌ "Trained an ML model for discharge summary generation" — summaries are an LLM pipeline (Gemini), not a model you trained. Say "designed an LLM pipeline" / "applied AI system."
- ❌ Deployed in a live hospital with real patients — it runs on MIMIC-IV (de-identified public research data) plus synthetic demo patients.
- ❌ The EWS Ward Monitor / NEWS2 scoring / drug-lab interaction engine — that's your teammate's module. You can say "integrated into a shared platform alongside an EWS ward-monitoring module," which is true and still credits the system scale.
- ❌ Any accuracy number you can't reproduce from `cost_ml_model/data/eval_*.csv`.

---

## SCREENSHOTS TO SHOW (portfolio / GitHub README)

Order them as a story — a patient moving through the product, not a feature dump:

1. **Doctor queue** (`frontend/doctor-queue.html`) — the work surface, patients awaiting summaries
2. **Patient dashboard** (`screens/doctor-dashboard.js`) — clinical data assembled from EHR
3. **AI review editor** (`screens/review-v2.js`) — *the money shot*: 15 generated sections with T1/T2/T3 verification flags inline. Capture one with a **T3 flag visible** — that single image communicates "AI with a safety layer" better than any bullet.
4. **Blocked sign-off** (`screens/signoff.js`) — the "🔒 Resolve T3 Flags First" state. Proves the gate is enforced, not decorative.
5. **Signed summary + signature** (`screens/signed.js`) — the accountable artifact
6. **Billing / cost estimate** (`frontend/billing.html`) — where the ML model surfaces to a user
7. **Model evaluation chart** — `cost_ml_model/eval_charts/diagnosis_band_before_after_mape.png` and `with_band_calibration_by_day.png`. Recruiters skim; a before/after accuracy chart reads instantly.

**Caption each screenshot with the engineering decision behind it**, not what's on screen. "Sign-off is hard-blocked until every critical flag is resolved" beats "Sign-off screen."
