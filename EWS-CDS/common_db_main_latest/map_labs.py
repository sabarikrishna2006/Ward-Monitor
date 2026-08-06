"""
map_labs.py  — v1
Enriched Embedding + LLM Validation Pipeline for MIMIC → Indian Lab Price Mapping
Uses shared clinical_enrichment.py engine.
LLM validation is invoked only when the top embedding score is below a threshold
(labs are usually unambiguous — no need to call Gemini for "Serum Sodium").
"""

import os, json, time
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
import sys
# Windows console default (cp1252) can't encode arrows/em-dashes used in print()
# statements below or in data-derived text — force UTF-8 with a safe fallback so
# no print() can crash the process (this killed the pipeline once already).
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
from clinical_enrichment import (normalize, enrich, build_enriched_string, load_cache, save_cache,
                                  embed_resumable, load_results_checkpoint, save_results_checkpoint)

# ── Config ────────────────────────────────────────────────────────────────────
with open(os.path.join(PROJECT_DIR, "pricing_config.json")) as f:
    config = json.load(f)

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)
llm_flash = genai.GenerativeModel("gemini-flash-latest")
llm_pro   = genai.GenerativeModel("gemini-pro-latest")

DL = r"c:\Users\ASUS\Downloads"
VERSION   = config["versions"]["lab_mapping"]
THRESHOLD = config["thresholds"]["lab_confidence"]
# Labs: only invoke LLM if top embedding score is < this (avoids unnecessary calls)
AUTO_ACCEPT_EMB = 0.88
CACHE_FILE = os.path.join(DL, "enrichment_cache.json")

VALIDATION_PROMPT = """You are a clinical laboratory specialist. Two lab tests may be the same under different names.

MIMIC Lab Test: "{us_lab}"
Category: {category} | Sample: {sample} | Organ: {organ} | Purpose: {purpose}

Top Candidate Lab Tests from Indian tariff (semantic similarity):
{candidates_str}

Rules:
- REJECT if sample types differ (Blood ≠ Urine ≠ CSF)
- REJECT if fundamentally different analytes (e.g., Sodium ≠ Potassium)
- ACCEPT if same analyte, even if name differs slightly (e.g., "Serum Na" = "Sodium, Serum")

Return ONLY JSON:
"best_match": exact candidate name from the list, or "None"
"confidence": float 0.0–1.0
"confidence_category": "High" (>=0.85), "Medium" (0.65–0.84), or "Low" (<0.65)
"category": predicted category (e.g., "Chemistry", "Haematology")
"reason": one sentence justification

JSON only:"""

def main():
    print("=" * 60)
    print("LAB MAPPING v1 — Enriched Embeddings")
    print("=" * 60)

    df_labs   = pd.read_csv(os.path.join(DL, "dcm_distinct_labs.csv"))
    df_kaggle = pd.read_csv(os.path.join(DL, "lab_prices.csv"))

    # Find price and name columns
    price_col = next((c for c in df_kaggle.columns if 'price' in c.lower() or 'cost' in c.lower() or 'rate' in c.lower()), None)
    name_col  = next((c for c in df_kaggle.columns if 'test' in c.lower() or 'name' in c.lower() or 'lab' in c.lower()), None)

    if not price_col or not name_col:
        print(f"Columns: {df_kaggle.columns.tolist()}")
        # fallback: first col = name, second = price
        name_col  = df_kaggle.columns[0]
        price_col = df_kaggle.columns[1]

    df_kaggle[price_col] = pd.to_numeric(df_kaggle[price_col], errors='coerce')
    df_kaggle = df_kaggle.dropna(subset=[price_col])

    global_mean = float(df_kaggle[price_col].mean())
    print(f"Kaggle labs: {len(df_kaggle)} | mean Rs. {global_mean:.2f}")
    print(f"Price: '{price_col}' | Name: '{name_col}'")

    # Category fallback
    cat_col = next((c for c in df_kaggle.columns if 'category' in c.lower() or 'type' in c.lower() or 'dept' in c.lower()), None)
    cat_means = {}
    if cat_col:
        cat_means = df_kaggle.groupby(cat_col)[price_col].mean().to_dict()
        print(f"Category fallback from '{cat_col}': {len(cat_means)} categories")

    cache = load_cache(CACHE_FILE)

    # Step 1 — Enrich Kaggle lab corpus
    kaggle_names = df_kaggle[name_col].astype(str).tolist()
    print(f"\n[1] Enriching Kaggle lab corpus ({len(kaggle_names)} tests)...")
    kaggle_enriched = []
    for i, name in enumerate(kaggle_names):
        ctx = enrich(name, "lab", cache, CACHE_FILE, llm_flash)
        kaggle_enriched.append(build_enriched_string(name, ctx, "lab"))
        if (i+1) % 100 == 0:
            print(f"   {i+1}/{len(kaggle_names)} enriched")
        time.sleep(0.02)

    print("\n[2] Embedding Kaggle lab corpus...")
    embedder = SentenceTransformer('ncbi/MedCPT-Query-Encoder')
    kag_emb  = embed_resumable(embedder, kaggle_enriched, os.path.join(DL, f"kaggle_emb_{VERSION}.npy"))
    kag_emb_n = kag_emb / np.linalg.norm(kag_emb, axis=1, keepdims=True)

    df_sample = df_labs
    print(f"\n[3] Processing {len(df_sample)} MIMIC labs...")
    llm_calls = 0

    CKPT_FILE = os.path.join(DL, f"lab_matching_ckpt_{VERSION}.json")
    _ckpt = load_results_checkpoint(CKPT_FILE)
    results, audit, _start_i = _ckpt["results"], _ckpt["audit"], _ckpt["done"]

    for i, (_, row) in enumerate(df_sample.iterrows()):
        if i < _start_i:
            continue
        us_lab  = str(row.get('label', row.iloc[0])).strip()
        fluid   = str(row.get('fluid', '')).strip()
        norm    = normalize(us_lab, "lab")

        ctx = enrich(norm, "lab", cache, CACHE_FILE, llm_flash)
        enriched_str = build_enriched_string(norm, ctx, "lab")

        us_emb = embedder.encode([enriched_str])
        us_emb_n = us_emb / np.linalg.norm(us_emb, axis=1, keepdims=True)
        scores = np.dot(us_emb_n, kag_emb_n.T)[0]

        top10 = [{"rank": r+1, "name": kaggle_names[j], "embedding_score": float(scores[j])}
                 for r, j in enumerate(np.argsort(scores)[-10:][::-1])]
        top_score = top10[0]['embedding_score'] if top10 else 0.0

        # Auto-accept if embedding is very strong (saves LLM calls)
        best, conf, cat, reason, llm_raw = top10[0]['name'], top_score, "High", "Auto-accepted: high embedding similarity", "{}"
        used_llm = False

        if top_score < AUTO_ACCEPT_EMB:
            used_llm = True
            llm_calls += 1
            cands_str = "\n".join(f"{c['rank']}. {c['name']} (sim={c['embedding_score']:.3f})" for c in top10)
            prompt = VALIDATION_PROMPT.format(
                us_lab=us_lab, category=ctx.get('category','Unknown'),
                sample=ctx.get('sample_type','Unknown'), organ=ctx.get('organ_system','Unknown'),
                purpose=ctx.get('clinical_purpose','Unknown'), candidates_str=cands_str
            )
            llm_json = {}
            for attempt in range(3):
                try:
                    r = llm_pro.generate_content(prompt, generation_config={"temperature":0.0,"response_mime_type":"application/json"}, request_options={"timeout": 30})
                    llm_raw  = r.text
                    llm_json = json.loads(llm_raw)
                    break
                except Exception as e:
                    time.sleep(3)
                    if attempt == 2:
                        llm_json = {"best_match":top10[0]['name'],"confidence":top_score,
                                    "confidence_category":"Low","category":ctx.get('category','Unknown'),
                                    "reason":f"API Error: {e}"}
            best   = llm_json.get("best_match", top10[0]['name'])
            conf   = float(llm_json.get("confidence", top_score))
            cat    = llm_json.get("confidence_category","Low")
            reason = llm_json.get("reason","")
        else:
            cat = "High"

        emb_s = next((c['embedding_score'] for c in top10 if c['name']==best), top_score)
        qual  = round((emb_s + conf + (1.0 if best!="None" else 0.0)) / 3.0, 4)

        fallback, fb_type = False, "None"
        final_name, final_price = "None", 0.0

        if best != "None" and conf >= THRESHOLD:
            mr = df_kaggle[df_kaggle[name_col] == best]
            if not mr.empty:
                final_price = float(mr.iloc[0][price_col])
                final_name  = best
        else:
            fallback = True
            pred_cat = ctx.get('category','Unknown')
            matched_cat = next((k for k in cat_means if any(
                w.lower() in str(k).lower() for w in pred_cat.split() if len(w) > 3)), None)
            if matched_cat:
                final_price = cat_means[matched_cat]
                fb_type = f"Category Average ({matched_cat})"
            else:
                final_price = global_mean
                fb_type = "Global Kaggle Lab Average"

        # Build Indian name with context
        fluid_tag = f" ({fluid})" if fluid and fluid.lower() not in ['nan',''] else ""
        indian_name = f"{ctx.get('standardized_name', us_lab)}{fluid_tag}" if final_name == "None" else final_name

        results.append({'us_lab_itemid': row.get('itemid',''),
                        'us_lab_label': us_lab, 'fluid': fluid,
                        'indian_lab_equivalent': indian_name,
                        'price_in_rupees': round(final_price, 2),
                        'pricing_source': fb_type if fallback else "Kaggle Lab Dataset Match"})

        audit.append({'Original Name': us_lab, 'Fluid': fluid, 'Normalized Name': norm,
                      'Category': ctx.get('category'), 'Sample Type': ctx.get('sample_type'),
                      'Organ System': ctx.get('organ_system'), 'Purpose': ctx.get('clinical_purpose'),
                      'Matched Name': best, 'Embedding Score': emb_s,
                      'LLM Called': used_llm, 'LLM Confidence': conf, 'Confidence Category': cat,
                      'Quality Score': qual, 'Reason': reason,
                      'Fallback Used': fallback, 'Fallback Type': fb_type,
                      'Needs Manual Review': conf < THRESHOLD,
                      'LLM Response': llm_raw, 'Top 10 Candidates': json.dumps(top10)})

        status = fb_type if fallback else "MATCH"
        llm_tag = " [LLM]" if used_llm else " [EMB]"
        print(f"[{i+1:>4}/{len(df_sample)}] {us_lab[:45]:<45} | {conf:.2f} {cat:<8}{llm_tag} | {status}")
        save_results_checkpoint(CKPT_FILE, results, audit, i + 1)
        time.sleep(0.1)

    out_m = os.path.join(DL, f"lab_mapping_{VERSION}.csv")
    out_a = os.path.join(DL, f"lab_audit_{VERSION}.csv")
    pd.DataFrame(results).to_csv(out_m, index=False)
    pd.DataFrame(audit).to_csv(out_a, index=False)

    df_r = pd.DataFrame(results); df_a = pd.DataFrame(audit)
    n_match = (df_r['pricing_source']=="Kaggle Lab Dataset Match").sum()
    print(f"\n{'='*60}\nDONE | Matches: {n_match}/100 | LLM calls: {llm_calls}/100 | Avg conf: {df_a['LLM Confidence'].mean():.3f}")
    print(f"Mapping → {out_m}\nAudit   → {out_a}")

    meta = {"domain":"labs","version":VERSION,
            "embedding_model":"ncbi/MedCPT-Query-Encoder","enrichment_model":"gemini-flash-latest",
            "validation_model":"gemini-pro-latest","embedding_strategy":"enriched_clinical_context",
            "auto_accept_embedding_threshold": AUTO_ACCEPT_EMB,
            "llm_confidence_threshold":THRESHOLD,"pricing_source":"Kaggle Lab Prices",
            "date":time.strftime("%Y-%m-%d %H:%M:%S"),"records_processed":len(df_r),
            "match_rate_pct":round(100*n_match/len(df_r),2),
            "llm_call_rate_pct":round(100*llm_calls/len(df_r),2),
            "mean_confidence":round(float(df_a['LLM Confidence'].mean()),4)}
    with open(os.path.join(DL,f"mapping_metadata_labs_{VERSION}.json"),'w') as f:
        json.dump(meta,f,indent=4)

if __name__ == "__main__":
    main()
