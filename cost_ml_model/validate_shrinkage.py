import pandas as pd
import numpy as np

static = pd.read_csv("data/dcm_admissions_static.csv")[["hadm_id", "primary_diagnosis"]]
bills = pd.read_csv("data/dcm_model_ready_data.csv")[["hadm_id", "total_bill_at_discharge"]].drop_duplicates("hadm_id")

df = static.merge(bills, on="hadm_id").dropna()
df = df[["primary_diagnosis", "total_bill_at_discharge"]]
df.columns = ["diagnosis", "cost"]

pop_avg = df["cost"].mean()
n_admissions = len(df)
K = 3

grp = df.groupby("diagnosis")["cost"]
sums = grp.sum()
counts = grp.count()

def loo_predictions(k):
    raw_preds, shrunk_preds, actuals, ns = [], [], [], []
    for diag, sub in df.groupby("diagnosis"):
        n = len(sub)
        total = sub["cost"].sum()
        for cost in sub["cost"]:
            n_others = n - 1
            sum_others = total - cost
            raw_loo = sum_others / n_others if n_others > 0 else pop_avg
            shrunk_loo = (n_others * (sum_others / n_others if n_others > 0 else 0) + k * pop_avg) / (n_others + k) if n_others > 0 else pop_avg
            raw_preds.append(raw_loo)
            shrunk_preds.append(shrunk_loo)
            actuals.append(cost)
            ns.append(n)
    return np.array(raw_preds), np.array(shrunk_preds), np.array(actuals), np.array(ns)

raw_preds, shrunk_preds, actuals, ns = loo_predictions(K)

raw_mae = np.mean(np.abs(raw_preds - actuals))
shrunk_mae = np.mean(np.abs(shrunk_preds - actuals))

print(f"Population average: Rs {pop_avg:,.0f}  |  Total admissions: {n_admissions}  |  Distinct diagnoses: {df['diagnosis'].nunique()}")
print()
print("Leave-one-out validation: 'if this admission's bill were unknown, how well would we have predicted it")
print("using ONLY the other admissions sharing its diagnosis' -- raw average of others vs shrunk average of others.")
print()
print(f"{'Overall (all admissions)':35s}  raw MAE = Rs {raw_mae:>10,.0f}   shrunk MAE = Rs {shrunk_mae:>10,.0f}   shrinkage {'WINS' if shrunk_mae<raw_mae else 'loses'} by Rs {abs(raw_mae-shrunk_mae):,.0f}")
print()

bins = [(1,1,"n=1 (single admission)"), (2,2,"n=2"), (3,5,"n=3-5"), (6,10,"n=6-10"), (11,10**9,"n=11+")]
for lo, hi, label in bins:
    mask = (ns >= lo) & (ns <= hi)
    if mask.sum() == 0:
        continue
    r_mae = np.mean(np.abs(raw_preds[mask] - actuals[mask]))
    s_mae = np.mean(np.abs(shrunk_preds[mask] - actuals[mask]))
    print(f"{label:35s}  raw MAE = Rs {r_mae:>10,.0f}   shrunk MAE = Rs {s_mae:>10,.0f}   n_admissions={mask.sum():5d}   shrinkage {'WINS' if s_mae<r_mae else 'loses'} by Rs {abs(r_mae-s_mae):,.0f} ({abs(r_mae-s_mae)/r_mae*100:.1f}%)")
