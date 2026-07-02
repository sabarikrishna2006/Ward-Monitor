"""
map_medicines.py  — v1
Enriched Embedding + LLM Validation Pipeline for MIMIC → Indian Medicine Mapping
Uses shared clinical_enrichment.py engine.
"""

import os, json, time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeoutError
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

# The SDK's own request_options={"timeout": N} is not always honored (observed a
# real hang past 30s on one item that blocked the whole pipeline indefinitely) —
# enforce a hard timeout from our side via a worker thread so a stuck call can
# never block progress past its retry budget.
_llm_executor = ThreadPoolExecutor(max_workers=2)

def _generate_with_hard_timeout(model, prompt, timeout=30):
    fut = _llm_executor.submit(
        model.generate_content, prompt,
        generation_config={"temperature": 0.0, "response_mime_type": "application/json"},
        request_options={"timeout": timeout},
    )
    return fut.result(timeout=timeout + 5)

DL = r"c:\Users\ASUS\Downloads"
VERSION   = config["versions"]["medicine_mapping"]
THRESHOLD = config["thresholds"]["medicine_confidence"]
CACHE_FILE = os.path.join(DL, "enrichment_cache.json")  # same shared cache

VALIDATION_PROMPT = """You are a senior clinical pharmacist mapping US hospital medications to Indian equivalents for billing.

US Medicine: "{us_med}"
Active Ingredient: {ingredient} | Drug Class: {drug_class} | Route: {route} | Indication: {indication}

Top Indian Medicine Candidates (semantic similarity):
{candidates_str}

Matching rules:
- ACCEPT if active ingredient is the same (strength mismatch is OK — use the Indian price)
- ACCEPT if same drug class AND same route AND same indication
- REJECT if route differs clinically (e.g., IV vs Oral for same drug is a different product)
- REJECT if paediatric-only medicine matched to adult or vice versa

Return ONLY JSON:
"best_match": exact Indian medicine name from the list, or "None"
"confidence": float 0.0–1.0
"confidence_category": "High" (>=0.85), "Medium" (0.65–0.84), or "Low" (<0.65)
"drug_class": predicted drug class of the US medicine
"reason": one sentence justification

JSON only:"""

def main():
    print("=" * 60)
    print("MEDICINE MAPPING v1 — Enriched Embeddings")
    print("=" * 60)

    df_meds   = pd.read_csv(os.path.join(DL, "dcm_distinct_medications.csv"))
    df_indian = pd.read_csv(os.path.join(DL, "indian_medicine_data.csv"))

    # Build Indian medicine price lookup — use "Price" or similar column
    price_col = None
    for col in df_indian.columns:
        if 'price' in col.lower() or 'mrp' in col.lower() or 'cost' in col.lower():
            price_col = col
            break
    if price_col is None:
        print(f"WARNING: No price column found. Columns: {df_indian.columns.tolist()}")
        return

    df_indian[price_col] = pd.to_numeric(df_indian[price_col], errors='coerce')
    df_indian = df_indian.dropna(subset=[price_col])

    # Name column
    name_col = None
    for col in df_indian.columns:
        if 'name' in col.lower() or 'medicine' in col.lower() or 'product' in col.lower():
            name_col = col
            break
    if name_col is None:
        name_col = df_indian.columns[0]

    global_mean = float(df_indian[price_col].mean())
    print(f"Indian medicines: {len(df_indian)} | mean Rs. {global_mean:.2f}")
    print(f"Price column: '{price_col}' | Name column: '{name_col}'")

    # Drug class fallback — compute mean price per drug class if column exists
    class_col = next((c for c in df_indian.columns if 'class' in c.lower() or 'type' in c.lower() or 'category' in c.lower()), None)
    class_means = {}
    if class_col:
        class_means = df_indian.groupby(class_col)[price_col].mean().to_dict()
        print(f"Drug class fallback available from column: '{class_col}' ({len(class_means)} classes)")

    cache = load_cache(CACHE_FILE)

    # For the 254k Indian corpus, we embed raw names directly (no Gemini enrichment).
    # Medicine names are self-describing. Enrichment only happens on MIMIC drugs (1,865 items).
    indian_names = df_indian[name_col].astype(str).tolist()
    print(f"\n[1] Embedding raw Indian medicine corpus ({len(indian_names)} medicines)...")
    print("    (No Gemini enrichment on corpus — too large. Raw names embedded directly.)")
    embedder = SentenceTransformer('ncbi/MedCPT-Query-Encoder')
    norm_cache = os.path.join(DL, f"indian_med_emb_{VERSION}_normalized.npy")
    if os.path.exists(norm_cache):
        print("    loading pre-normalized embedding cache (skips the 254k-row renormalization)")
        indian_emb_n = np.load(norm_cache)
    else:
        indian_emb = embed_resumable(embedder, indian_names, os.path.join(DL, f"indian_med_emb_{VERSION}.npy"), save_every=2000)
        # Normalize in chunks rather than one 254k-row op, and cache the result —
        # this single-shot division is the exact point the process kept getting
        # killed at on every restart (repeatedly redone for no reason once the
        # raw embeddings were already cached).
        indian_emb_n = np.empty(indian_emb.shape, dtype=np.float32)
        CHUNK = 20000
        for _i in range(0, indian_emb.shape[0], CHUNK):
            _j = min(_i + CHUNK, indian_emb.shape[0])
            _block = np.asarray(indian_emb[_i:_j])
            _norms = np.linalg.norm(_block, axis=1, keepdims=True)
            _norms[_norms == 0] = 1.0
            indian_emb_n[_i:_j] = _block / _norms
        np.save(norm_cache, indian_emb_n)

    df_sample = df_meds
    print(f"\n[2] Enriching {len(df_sample)} MIMIC medications with Gemini Flash...")


    CKPT_FILE = os.path.join(DL, f"medicine_matching_ckpt_{VERSION}.json")
    _ckpt = load_results_checkpoint(CKPT_FILE)
    results, audit, _start_i = _ckpt["results"], _ckpt["audit"], _ckpt["done"]

    for i, (_, row) in enumerate(df_sample.iterrows()):
        if i < _start_i:
            continue
        us_drug = str(row.get('drug', row.iloc[0])).strip()
        norm    = normalize(us_drug, "medicine")

        ctx = enrich(norm, "medicine", cache, CACHE_FILE, llm_flash)
        enriched_str = build_enriched_string(norm, ctx, "medicine")

        us_emb = embedder.encode([enriched_str])
        us_emb_n = us_emb / np.linalg.norm(us_emb, axis=1, keepdims=True)
        scores = np.dot(us_emb_n, indian_emb_n.T)[0]

        top20 = [{"rank": r+1, "name": indian_names[j], "embedding_score": float(scores[j])}
                 for r, j in enumerate(np.argsort(scores)[-20:][::-1])]
        cands_str = "\n".join(f"{c['rank']}. {c['name']} (sim={c['embedding_score']:.3f})" for c in top20)

        prompt = VALIDATION_PROMPT.format(
            us_med=us_drug,
            ingredient=ctx.get('active_ingredient','Unknown'),
            drug_class=ctx.get('drug_class','Unknown'),
            route=ctx.get('route','Unknown'),
            indication=ctx.get('common_indication','Unknown'),
            candidates_str=cands_str
        )

        llm_raw, llm_json = "{}", {}
        for attempt in range(3):
            try:
                r = _generate_with_hard_timeout(llm_pro, prompt, timeout=30)
                llm_raw  = r.text
                llm_json = json.loads(llm_raw)
                break
            except Exception as e:
                time.sleep(3)
                if attempt == 2:
                    llm_json = {"best_match":"None","confidence":0.0,"confidence_category":"Low",
                                "drug_class":ctx.get('drug_class','Unknown'),"reason":f"API Error: {e}"}

        best       = llm_json.get("best_match","None")
        conf       = float(llm_json.get("confidence",0.0))
        cat        = llm_json.get("confidence_category","Low")
        drug_class = llm_json.get("drug_class", ctx.get("drug_class","Unknown"))
        reason     = llm_json.get("reason","")
        emb_s      = next((c['embedding_score'] for c in top20 if c['name']==best), 0.0)
        qual       = round((emb_s + conf + (1.0 if best!="None" else 0.0)) / 3.0, 4)

        fallback, fb_type = False, "None"
        final_name, final_price = "None", 0.0

        if best != "None" and conf >= THRESHOLD:
            mr = df_indian[df_indian[name_col] == best]
            if not mr.empty:
                final_price = float(mr.iloc[0][price_col])
                final_name  = best
        else:
            fallback = True
            matched_class = next((k for k in class_means if any(
                w.lower() in str(k).lower() for w in drug_class.split() if len(w) > 4)), None)
            if matched_class:
                final_price = class_means[matched_class]
                fb_type = f"Drug Class Average ({matched_class})"
            else:
                final_price = global_mean
                fb_type = "Global Indian Medicine Average"

        results.append({'us_medicine': us_drug,
                        'indian_medicine_equivalent': final_name,
                        'active_ingredient': ctx.get('active_ingredient','Unknown'),
                        'drug_class': drug_class,
                        'price_in_rupees': round(final_price, 2),
                        'pricing_source': fb_type if fallback else "Indian Medicine Dataset Match"})

        audit.append({'Original Name': us_drug, 'Normalized Name': norm,
                      'Active Ingredient': ctx.get('active_ingredient'),
                      'Drug Class': ctx.get('drug_class'), 'Route': ctx.get('route'),
                      'Indication': ctx.get('common_indication'),
                      'Matched Name': best, 'Embedding Score': emb_s,
                      'LLM Confidence': conf, 'Confidence Category': cat,
                      'Quality Score': qual, 'Reason': reason,
                      'Fallback Used': fallback, 'Fallback Type': fb_type,
                      'Needs Manual Review': conf < THRESHOLD,
                      'LLM Prompt': prompt, 'LLM Response': llm_raw,
                      'Top 20 Candidates': json.dumps(top20)})

        status = fb_type if fallback else "MATCH"
        print(f"[{i+1:>4}/{len(df_sample)}] {us_drug[:45]:<45} | {conf:.2f} {cat:<8} | {status}")
        save_results_checkpoint(CKPT_FILE, results, audit, i + 1)
        time.sleep(0.4)

    out_m = os.path.join(DL, f"medicine_mapping_{VERSION}.csv")
    out_a = os.path.join(DL, f"medicine_audit_{VERSION}.csv")
    pd.DataFrame(results).to_csv(out_m, index=False)
    pd.DataFrame(audit).to_csv(out_a, index=False)

    df_r = pd.DataFrame(results); df_a = pd.DataFrame(audit)
    n_match = (df_r['pricing_source']=="Indian Medicine Dataset Match").sum()
    print(f"\n{'='*60}\nDONE | Matches: {n_match}/100 | Avg conf: {df_a['LLM Confidence'].mean():.3f}")
    print(f"Mapping → {out_m}\nAudit   → {out_a}")

    meta = {"domain":"medicines","version":VERSION,
            "embedding_model":"ncbi/MedCPT-Query-Encoder","enrichment_model":"gemini-flash-latest",
            "validation_model":"gemini-pro-latest","embedding_strategy":"enriched_clinical_context",
            "threshold":THRESHOLD,"pricing_source":"Indian Medicine Data (Kaggle)",
            "date":time.strftime("%Y-%m-%d %H:%M:%S"),"records_processed":len(df_r),
            "match_rate_pct":round(100*n_match/len(df_r),2),
            "mean_confidence":round(float(df_a['LLM Confidence'].mean()),4)}
    with open(os.path.join(DL,f"mapping_metadata_medicines_{VERSION}.json"),'w') as f:
        json.dump(meta,f,indent=4)

if __name__ == "__main__":
    main()
