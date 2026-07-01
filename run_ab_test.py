import os, json, time
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from clinical_enrichment import normalize, enrich, build_enriched_string, load_cache

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
genai.configure(api_key=GEMINI_API_KEY)
llm_flash = genai.GenerativeModel("gemini-flash-latest")
llm_pro   = genai.GenerativeModel("gemini-pro-latest")

DL = r"c:\Users\ASUS\Downloads"
CACHE_FILE = os.path.join(DL, "enrichment_cache.json")

VALIDATION_PROMPT = """You are a senior clinician mapping US inpatient procedures to Indian PMJAY packages.
US Procedure: "{us_title}"
Specialty: {specialty} | Organ: {organ} | Intent: {intent} | Invasiveness: {invasiveness}
Top PMJAY Candidates:
{candidates_str}
Return ONLY JSON:
"best_match": exact PMJAY name from the list, or "None",
"confidence": float 0.0-1.0
"""

def get_gemini_validation(us_title, ctx, top5):
    cands_str = "\n".join(f"{c['rank']}. {c['name']} (sim={c['sim']:.3f})" for c in top5)
    prompt = VALIDATION_PROMPT.format(
        us_title=us_title, specialty=ctx.get('specialty',''),
        organ=ctx.get('organ_system',''), intent=ctx.get('intent',''),
        invasiveness=ctx.get('invasiveness',''), candidates_str=cands_str
    )
    for _ in range(3):
        try:
            r = llm_pro.generate_content(prompt, generation_config={"temperature":0.0,"response_mime_type":"application/json"})
            return json.loads(r.text)
        except:
            time.sleep(2)
    return {"best_match":"None", "confidence":0.0}

def main():
    print("Loading models...")
    model_a = SentenceTransformer('all-MiniLM-L6-v2')
    model_b = SentenceTransformer('ncbi/MedCPT-Query-Encoder')
    
    df_pmjay = pd.read_csv(os.path.join(DL, "pmjay_assam_procedures.csv")).dropna(subset=['AB PM - JAY Procedure Name'])
    pmjay_names = df_pmjay['AB PM - JAY Procedure Name'].tolist()
    
    cache = load_cache(CACHE_FILE)
    
    print("Enriching PMJAY corpus...")
    pmjay_enriched = []
    for name in pmjay_names:
        ctx = enrich(name, "procedure", cache, CACHE_FILE, llm_flash)
        pmjay_enriched.append(build_enriched_string(name, ctx, "procedure"))
        
    print("Embedding PMJAY corpus (Model A)...")
    emb_a = model_a.encode(pmjay_enriched, batch_size=64, show_progress_bar=False)
    emb_a = emb_a / np.linalg.norm(emb_a, axis=1, keepdims=True)
    
    print("Embedding PMJAY corpus (Model B)...")
    emb_b = model_b.encode(pmjay_enriched, batch_size=64, show_progress_bar=False)
    emb_b = emb_b / np.linalg.norm(emb_b, axis=1, keepdims=True)
    
    df_test = pd.read_csv(os.path.join(DL, "ab_test_procedures.csv"))
    print(f"Testing {len(df_test)} procedures from cohort...")
    
    results = []
    
    for i, row in df_test.iterrows():
        us_title = str(row['long_title'])
        norm = normalize(us_title, "procedure")
        ctx = enrich(norm, "procedure", cache, CACHE_FILE, llm_flash)
        estr = build_enriched_string(norm, ctx, "procedure")
        
        # Pipeline A
        va = model_a.encode([estr])
        va = va / np.linalg.norm(va, axis=1, keepdims=True)
        scores_a = np.dot(va, emb_a.T)[0]
        top5_a = [{"rank": r+1, "name": pmjay_names[j], "sim": float(scores_a[j])} 
                  for r, j in enumerate(np.argsort(scores_a)[-5:][::-1])]
        val_a = get_gemini_validation(us_title, ctx, top5_a)
        
        # Pipeline B
        vb = model_b.encode([estr])
        vb = vb / np.linalg.norm(vb, axis=1, keepdims=True)
        scores_b = np.dot(vb, emb_b.T)[0]
        top5_b = [{"rank": r+1, "name": pmjay_names[j], "sim": float(scores_b[j])} 
                  for r, j in enumerate(np.argsort(scores_b)[-5:][::-1])]
        val_b = get_gemini_validation(us_title, ctx, top5_b)
        
        discrepancy = (val_a.get("best_match") != val_b.get("best_match"))
        
        results.append({
            "US Procedure": us_title,
            "Discrepancy": discrepancy,
            "Model A (MiniLM) Match": val_a.get("best_match"),
            "Model A Conf": val_a.get("confidence"),
            "Model A Top 5": " | ".join([c['name'] for c in top5_a]),
            "Model B (MedCPT) Match": val_b.get("best_match"),
            "Model B Conf": val_b.get("confidence"),
            "Model B Top 5": " | ".join([c['name'] for c in top5_b])
        })
        
        if discrepancy:
            print(f"[!] Discrepancy on: {us_title[:40]}")
            
    df_res = pd.DataFrame(results)
    df_res.to_csv(os.path.join(DL, "ab_test_discrepancies.csv"), index=False)
    print(f"\nA/B Test complete. Found {df_res['Discrepancy'].sum()} discrepancies.")
    print(f"Results saved to ab_test_discrepancies.csv")

if __name__ == "__main__":
    main()
