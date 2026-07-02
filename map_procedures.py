"""
map_procedures.py  — v2
Enriched Embedding + LLM Validation Pipeline for MIMIC → PMJAY Procedure Mapping
Uses shared clinical_enrichment.py engine.
"""

import os, json, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
import sys
# Windows console default (cp1252) can't encode arrows/em-dashes used in print()
# statements below or in data-derived text — this crashed the pipeline right
# after saving results, killing the whole run_all.py wrapper. Force UTF-8 with
# a safe fallback so no print() can ever crash the process again.
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
from clinical_enrichment import (normalize, enrich, build_enriched_string, load_cache, save_cache,
                                  embed_resumable, load_results_checkpoint, save_results_checkpoint)

# ── Config ───────────────────────────────────────────────────────────────────
with open(os.path.join(PROJECT_DIR, "pricing_config.json")) as f:
    config = json.load(f)

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)
llm_flash = genai.GenerativeModel("gemini-flash-latest")
llm_pro   = genai.GenerativeModel("gemini-pro-latest")

# The SDK's request_options={"timeout": N} is not always honored (observed a real
# hang that blocked the whole pipeline indefinitely on one item) — enforce a hard
# timeout from our side via a worker thread so a stuck call can never block
# progress past its retry budget.
_llm_executor = ThreadPoolExecutor(max_workers=2)

def _generate_with_hard_timeout(model, prompt, timeout=30):
    fut = _llm_executor.submit(
        model.generate_content, prompt,
        generation_config={"temperature": 0.0, "response_mime_type": "application/json"},
        request_options={"timeout": timeout},
    )
    return fut.result(timeout=timeout + 5)

DL = r"c:\Users\ASUS\Downloads"
VERSION   = config["versions"]["procedure_mapping"]
THRESHOLD = config["thresholds"]["procedure_confidence"]

CACHE_FILE = os.path.join(DL, "enrichment_cache.json")  # unified cache for all domains

VALIDATION_PROMPT = """You are a senior clinician mapping US inpatient procedures to Indian PMJAY packages.

US Procedure: "{us_title}"
Specialty: {specialty} | Organ: {organ} | Intent: {intent} | Invasiveness: {invasiveness}

Top PMJAY Candidates (semantic similarity):
{candidates_str}

Hard rules — REJECT if:
- Organ systems differ (Heart ≠ Brain, Kidney ≠ Eye, etc.)
- Intent differs (Diagnostic ≠ Therapeutic) with no strong justification
- Specialties are clinically unrelated

Return ONLY JSON:
"best_match": exact PMJAY name from the list, or "None"
"confidence": float 0.0–1.0
"confidence_category": "High" (>=0.85), "Medium" (0.65–0.84), or "Low" (<0.65)
"specialty": predicted specialty of US procedure
"reason": one sentence clinical justification or rejection reason

JSON only:"""

def main():
    print("=" * 60)
    print("PROCEDURE MAPPING v2 — Enriched Embeddings")
    print("=" * 60)

    df_procs = pd.read_csv(os.path.join(DL, "dcm_distinct_procedures.csv"))
    df_pmjay = pd.read_csv(os.path.join(DL, "pmjay_assam_procedures.csv"))
    df_pmjay['clean_price'] = (df_pmjay['Package Price'].astype(str)
                                .str.replace(',','',regex=False)
                                .str.extract(r'(\d+)').astype(float))
    df_pmjay = df_pmjay.dropna(subset=['AB PM - JAY Procedure Name','clean_price'])

    specialty_means = df_pmjay.groupby('Specialty')['clean_price'].mean().to_dict()
    global_mean = float(df_pmjay['clean_price'].mean())
    print(f"PMJAY: {len(df_pmjay)} procedures | mean Rs. {global_mean:.0f}")

    cache = load_cache(CACHE_FILE)

    # Step 1 — Enrich & embed PMJAY corpus
    print(f"\n[1] Enriching PMJAY corpus ({len(df_pmjay)} procedures)...")
    pmjay_names = df_pmjay['AB PM - JAY Procedure Name'].tolist()
    pmjay_enriched = []
    for i, name in enumerate(pmjay_names):
        ctx = enrich(name, "procedure", cache, CACHE_FILE, llm_flash)
        pmjay_enriched.append(build_enriched_string(name, ctx, "procedure"))
        if (i+1) % 100 == 0:
            print(f"   {i+1}/{len(pmjay_names)} enriched")
        time.sleep(0.03)

    print("\n[2] Embedding PMJAY corpus...")
    embedder = SentenceTransformer('ncbi/MedCPT-Query-Encoder')
    pmjay_emb = embed_resumable(embedder, pmjay_enriched, os.path.join(DL, f"pmjay_emb_{VERSION}.npy"))
    pmjay_emb_n = pmjay_emb / np.linalg.norm(pmjay_emb, axis=1, keepdims=True)

    # Step 3 — Process MIMIC (100 for audit sample)
    df_sample = df_procs
    print(f"\n[3] Processing {len(df_sample)} MIMIC procedures...")

    CKPT_FILE = os.path.join(DL, f"procedure_matching_ckpt_{VERSION}.json")
    _ckpt = load_results_checkpoint(CKPT_FILE)
    results, audit, _start_i = _ckpt["results"], _ckpt["audit"], _ckpt["done"]

    for i, (_, row) in enumerate(df_sample.iterrows()):
        if i < _start_i:
            continue
        us_code  = row['icd_code']
        us_title = str(row['long_title']).strip()
        norm     = normalize(us_title, "procedure")

        ctx = enrich(norm, "procedure", cache, CACHE_FILE, llm_flash)
        enriched_str = build_enriched_string(norm, ctx, "procedure")

        us_emb = embedder.encode([enriched_str])
        us_emb_n = us_emb / np.linalg.norm(us_emb, axis=1, keepdims=True)
        scores = np.dot(us_emb_n, pmjay_emb_n.T)[0]

        top20 = [{"rank": r+1, "name": pmjay_names[j], "embedding_score": float(scores[j])}
                 for r, j in enumerate(np.argsort(scores)[-20:][::-1])]
        cands_str = "\n".join(f"{c['rank']}. {c['name']} (sim={c['embedding_score']:.3f})" for c in top20)

        prompt = VALIDATION_PROMPT.format(
            us_title=us_title,
            specialty=ctx.get('specialty','Unknown'),
            organ=ctx.get('organ_system','Unknown'),
            intent=ctx.get('intent','Unknown'),
            invasiveness=ctx.get('invasiveness','Unknown'),
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
                                "specialty":ctx.get('specialty','Unknown'),"reason":f"API Error: {e}"}

        best   = llm_json.get("best_match","None")
        conf   = float(llm_json.get("confidence",0.0))
        cat    = llm_json.get("confidence_category","Low")
        spec   = llm_json.get("specialty",ctx.get("specialty","Unknown"))
        reason = llm_json.get("reason","")
        emb_s  = next((c['embedding_score'] for c in top20 if c['name']==best), 0.0)
        qual   = round((emb_s + conf + (1.0 if best!="None" else 0.0)) / 3.0, 4)

        # Threshold + intelligent fallback
        fallback, fb_type = False, "None"
        final_name, final_price = "None", 0.0

        if best != "None" and conf >= THRESHOLD:
            mr = df_pmjay[df_pmjay['AB PM - JAY Procedure Name'] == best]
            if not mr.empty:
                final_price = float(mr.iloc[0]['clean_price'])
                final_name  = best
        else:
            fallback = True
            matched = next((k for k in specialty_means if any(
                w.lower() in k.lower() for w in spec.split() if len(w) > 4)), None)
            if matched:
                final_price = specialty_means[matched]
                fb_type = f"Specialty Average ({matched})"
            else:
                final_price = global_mean
                fb_type = "Global PMJAY Average"

        results.append({'us_procedure_code': us_code, 'us_procedure_title': us_title,
                        'indian_procedure_equivalent': final_name,
                        'price_in_rupees': round(final_price,2),
                        'pricing_source': fb_type if fallback else "PMJAY Dataset Match"})

        audit.append({'Original Name': us_title, 'Normalized Name': norm,
                      'Specialty': ctx.get('specialty'), 'Organ System': ctx.get('organ_system'),
                      'Intent': ctx.get('intent'), 'Invasiveness': ctx.get('invasiveness'),
                      'Indication': ctx.get('typical_indication'),
                      'Matched Name': best, 'Embedding Score': emb_s,
                      'LLM Confidence': conf, 'Confidence Category': cat,
                      'Quality Score': qual, 'Reason': reason,
                      'Fallback Used': fallback, 'Fallback Type': fb_type,
                      'Needs Manual Review': conf < THRESHOLD,
                      'LLM Prompt': prompt, 'LLM Response': llm_raw,
                      'Top 20 Candidates': json.dumps(top20)})

        status = fb_type if fallback else "MATCH"
        print(f"[{i+1:>4}/{len(df_sample)}] {us_title[:50]:<50} | {conf:.2f} {cat:<8} | {status}")
        save_results_checkpoint(CKPT_FILE, results, audit, i + 1)
        time.sleep(0.4)

    # Save
    out_m = os.path.join(DL, f"procedure_mapping_{VERSION}.csv")
    out_a = os.path.join(DL, f"procedure_audit_{VERSION}.csv")
    pd.DataFrame(results).to_csv(out_m, index=False)
    pd.DataFrame(audit).to_csv(out_a, index=False)

    df_r = pd.DataFrame(results); df_a = pd.DataFrame(audit)
    n_match = (df_r['pricing_source']=="PMJAY Dataset Match").sum()
    print(f"\n{'='*60}\nDONE | Matches: {n_match}/100 | Avg conf: {df_a['LLM Confidence'].mean():.3f}")
    print(f"Mapping → {out_m}\nAudit   → {out_a}")

    meta = {"domain":"procedures","version":VERSION,
            "embedding_model":"ncbi/MedCPT-Query-Encoder","enrichment_model":"gemini-flash-latest",
            "validation_model":"gemini-pro-latest","embedding_strategy":"enriched_clinical_context",
            "threshold":THRESHOLD,"pricing_source":"PMJAY Assam",
            "date":time.strftime("%Y-%m-%d %H:%M:%S"),"records_processed":len(df_r),
            "match_rate_pct":round(100*n_match/len(df_r),2),
            "mean_confidence":round(float(df_a['LLM Confidence'].mean()),4)}
    with open(os.path.join(DL,f"mapping_metadata_procedures_{VERSION}.json"),'w') as f:
        json.dump(meta,f,indent=4)

if __name__ == "__main__":
    main()
