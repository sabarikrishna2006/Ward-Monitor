"""
Stage 17 — Cell C of the architecture ablation: ONE shared-trunk MLP with seven
output heads, trained with the masked cross-entropy loss from the professor's own
paper (Vishnu TV, Diksha, Malhotra, Vig & Shroff, arXiv:1903.09795).

WHAT THE PAPER ACTUALLY SPECIFIES (Fig 1c, Eq 2-5), so this can be defended:
  * ONE network. Input -> shared hidden layers -> a SINGLE sigmoid layer with K
    units (their Eq 3: `y_hat = sigma(W_C z_T^L + b_C)`). Not K networks.
  * Losses are SUMMED and averaged over the K sub-problems (Eq 3), so one backward
    pass updates the shared trunk using gradient from every interval at once. This
    is the "learning from each other" the professor asked for.
  * Censoring is handled by MASKING (Eq 4-5): for a censored instance the targets
    at and beyond the censoring interval are `unknown`; those units are dropped
    from the loss sum and the normaliser changes from K to K' (that instance's own
    count of known sub-problems). Not zero-filled, not dropped from the batch.

TWO DELIBERATE DIVERGENCES FROM THE PAPER, both defensible, state them explicitly:

  1. MLP trunk, not LSTM. The paper consumes a raw multivariate time series. This
     pipeline's 55 features are ALREADY rolling-window aggregates (means, mins,
     maxes, slopes over a 6h look-back), i.e. the temporal encoding an LSTM would
     learn has been done by hand in 02_build_features.py. Feeding pre-aggregated
     features to an LSTM would give it a sequence of length 1.

  2. Heads predict CONDITIONAL HAZARDS, not the paper's cumulative targets
     (their Eq 2: y_j = 1 if the event has happened by cutpoint j). Reason: with
     hazards, S(c_j) = S(c_{j-1}) * (1 - h_j) is a running product of terms in
     [0,1], so the survival curve is non-increasing BY CONSTRUCTION. The paper's
     cumulative form has no such guarantee and can emit a non-monotone curve.
     `18_mlp_cumulative_train.py` builds the paper's literal form so the two
     parameterisations can be compared rather than asserted.

Everything else is held identical to cells A and B — same features, same stable
patient-level split, same person-period masking, same per-interval isotonic
calibration, same running-product reconstruction, same output schema — so any
difference is attributable to the architecture alone.

Run: PYTHONUTF8=1 EWS_TAG=news2 py -3 17_mlp_ordinal_train.py
     PYTHONUTF8=1 EWS_TAG=news2 py -3 17_mlp_ordinal_train.py --ensemble 6
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import pickle

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.isotonic import IsotonicRegression

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mlp_ordinal")

_t3 = importlib.import_module("03_train")
_t9 = importlib.import_module("09_focused_train")
_t12 = importlib.import_module("12_ordinal_train")
three_way_split = _t3.three_way_split
news2_feature_cols, news2_ruler_time = _t9.news2_feature_cols, _t9.news2_ruler_time
reconstruct_survival = _t12.reconstruct_survival
conditional_expected_time_24h = _t12.conditional_expected_time_24h
cindex = _t12.cindex
cluster_bootstrap_cindex_ci = _t12.cluster_bootstrap_cindex_ci

META = ["stay_id", "hadm_id", "subject_id", "anchor_time", "T_hours", "event",
        "cause", "dcm_flag", "news2_at_anchor"]

HIDDEN = (128, 64)
DROPOUT = 0.2
LR = 1e-3
WEIGHT_DECAY = 1e-5
BATCH = 1024
MAX_EPOCHS = 60
PATIENCE = 8

# Mutable copies so --lr/--hidden/--patience can override the defaults for the
# validation-loss sweep in `sweep()`. Selection NEVER touches test data: the grid
# is scored on the calibration split's masked BCE, which is the same quantity
# early stopping already uses.
CFG = dict(hidden=HIDDEN, dropout=DROPOUT, lr=LR, weight_decay=WEIGHT_DECAY,
           batch=BATCH, max_epochs=MAX_EPOCHS, patience=PATIENCE)


# ══════════════════════════════════════════════════════════════════════════
# 1. Targets + mask — the paper's Eq 4/5, as dense matrices
# ══════════════════════════════════════════════════════════════════════════
def build_target_and_mask(df: pd.DataFrame, horizons: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Per anchor, return (Y, M) each of shape (n, K) for the CONDITIONAL-HAZARD form.

    For interval j spanning (c_{j-1}, c_j], with T = time-to-event/censoring:

      M=0 (masked, contributes NO loss term):
        - not at risk: T <= c_{j-1}. The patient already failed or already left in
          an earlier interval, so there is nothing to predict here.
        - censored partway through: event=0 and c_{j-1} < T < c_j. We genuinely do
          not know whether they would have failed in the rest of this interval.
          This is the paper's `unknown` (Eq 4), and it also kills every LATER
          interval for that anchor.
      M=1, Y=1: event=1 and c_{j-1} < T <= c_j   -> failed inside this interval
      M=1, Y=0: survived this interval outright   -> event=1 with T > c_j, or
                                                     event=0 with T >= c_j

    This reproduces exactly the same (row, interval) inclusion set as
    12_ordinal_train.build_person_period_table -- asserted in _selftest() -- but
    as a dense mask so one network can be trained on all intervals at once.
    K' in the paper's Eq 5 is then simply M.sum(axis=1), per row.
    """
    cut = [0.0] + [float(h) for h in horizons]
    T = df["T_hours"].to_numpy(dtype=float)
    E = df["event"].to_numpy().astype(bool)
    n, K = len(df), len(horizons)
    Y = np.zeros((n, K), dtype=np.float32)
    M = np.zeros((n, K), dtype=np.float32)

    alive = np.ones(n, dtype=bool)          # still in the risk set from earlier intervals
    for j in range(1, K + 1):
        c_prev, c_j = cut[j - 1], cut[j]
        at_risk = alive & (T > c_prev)
        fails = at_risk & E & (T <= c_j)
        survives = at_risk & ((E & (T > c_j)) | (~E & (T >= c_j)))
        unknown = at_risk & (~E) & (T < c_j)

        M[fails | survives, j - 1] = 1.0
        Y[fails, j - 1] = 1.0
        alive = at_risk & ~(fails | unknown)     # failures and censorings both exit
    return Y, M


# ══════════════════════════════════════════════════════════════════════════
# 2. The network — one trunk, K heads (the paper's Fig 1c)
# ══════════════════════════════════════════════════════════════════════════
class MultiHeadHazard(nn.Module):
    """Shared trunk + K independent linear heads -> K conditional hazards.

    The K heads are separate Linear(64 -> 1) layers rather than one Linear(64 -> K)
    purely for readability; they are mathematically the same thing (a single dense
    layer with K outputs), which is what the paper's Eq 3 specifies. What matters
    is that everything BELOW the heads is shared, so gradient from every interval
    updates the same representation.
    """

    def __init__(self, n_features: int, n_heads: int, hidden=HIDDEN, dropout=DROPOUT):
        super().__init__()
        layers, prev = [], n_features
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.BatchNorm1d(h), nn.ReLU(), nn.Dropout(dropout)]
            prev = h
        self.trunk = nn.Sequential(*layers)
        self.heads = nn.ModuleList([nn.Linear(prev, 1) for _ in range(n_heads)])

    def forward(self, x):
        z = self.trunk(x)
        return torch.cat([head(z) for head in self.heads], dim=1)   # LOGITS (n, K)


def masked_bce(logits, Y, M, eps=1e-7):
    """The paper's Eq 5, batched.

        L = mean over rows of  -1/K'_i * sum_j M_ij * BCE(p_ij, y_ij)

    Two details that matter and are easy to get wrong:
      * the normaliser is PER ROW (K'_i = M_i.sum()), not the global K. A patient
        censored after 2 intervals is averaged over 2 terms, not 7 -- otherwise
        heavily-censored patients would contribute a systematically smaller
        gradient purely because they were censored.
      * rows with K'_i = 0 (masked everywhere) are excluded rather than dividing
        by zero.
    """
    per_term = nn.functional.binary_cross_entropy_with_logits(logits, Y, reduction="none")
    per_row = (per_term * M).sum(dim=1)
    k_prime = M.sum(dim=1)
    valid = k_prime > 0
    if not valid.any():
        return logits.sum() * 0.0
    return (per_row[valid] / k_prime[valid].clamp(min=eps)).mean()


def train_one(Xtr, Ytr, Mtr, Xva, Yva, Mva, seed: int, n_heads: int, verbose=True):
    """Train a single network. `seed` controls BOTH weight init and batch shuffling
    -- the two sources of run-to-run variation the paper's ensemble (its Section 5)
    deliberately exploits to estimate predictive uncertainty."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    model = MultiHeadHazard(Xtr.shape[1], n_heads, hidden=tuple(CFG["hidden"]),
                            dropout=CFG["dropout"])
    opt = torch.optim.AdamW(model.parameters(), lr=CFG["lr"], weight_decay=CFG["weight_decay"])
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=3)

    Xtr_t, Ytr_t, Mtr_t = map(torch.from_numpy, (Xtr, Ytr, Mtr))
    Xva_t, Yva_t, Mva_t = map(torch.from_numpy, (Xva, Yva, Mva))
    n = len(Xtr_t)
    g = torch.Generator().manual_seed(seed)

    best, best_state, bad = float("inf"), None, 0
    for epoch in range(CFG["max_epochs"]):
        model.train()
        perm = torch.randperm(n, generator=g)
        tot = 0.0
        for i in range(0, n, CFG["batch"]):
            b = perm[i:i + CFG["batch"]]
            if len(b) < 2:            # BatchNorm needs >1 sample
                continue
            opt.zero_grad()
            loss = masked_bce(model(Xtr_t[b]), Ytr_t[b], Mtr_t[b])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            tot += float(loss.detach()) * len(b)
        model.eval()
        with torch.no_grad():
            vl = float(masked_bce(model(Xva_t), Yva_t, Mva_t))
        sched.step(vl)
        if vl < best - 1e-5:
            best, bad = vl, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
        if verbose and (epoch % 5 == 0 or bad >= CFG["patience"]):
            log.info("  seed=%d epoch %2d  train_loss=%.5f  val_loss=%.5f  (best %.5f, bad %d)",
                     seed, epoch, tot / max(n, 1), vl, best, bad)
        if bad >= CFG["patience"]:
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model, best


def predict_hazards(model, X: np.ndarray, batch=8192) -> np.ndarray:
    out = []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            out.append(torch.sigmoid(model(torch.from_numpy(X[i:i + batch]))).numpy())
    return np.vstack(out) if out else np.zeros((0, len(config.HORIZONS_H)))


# ══════════════════════════════════════════════════════════════════════════
def main(n_ensemble: int = 1, tag_suffix: str = ""):
    cutpoints = [0.0] + [float(h) for h in config.HORIZONS_H]
    K = len(config.HORIZONS_H)
    model_dir = config.tpath(f"models_mlp_ordinal{tag_suffix}")
    os.makedirs(model_dir, exist_ok=True)

    df = pd.read_parquet(config.tpath("features.parquet"))
    feats = news2_feature_cols(df)
    tr_i, cal_i, te_i = three_way_split(df)
    tr, cal, te = df.iloc[tr_i].copy(), df.iloc[cal_i].copy(), df.iloc[te_i].copy()
    log.info("split: train=%d calib=%d test=%d (subjects %d/%d/%d)", len(tr), len(cal), len(te),
             tr.subject_id.nunique(), cal.subject_id.nunique(), te.subject_id.nunique())

    # standardisation fitted on TRAIN ONLY -- calib/test statistics never leak in
    Xtr_raw = tr[feats].astype(float).values
    mu, sd = np.nanmean(Xtr_raw, axis=0), np.nanstd(Xtr_raw, axis=0)
    sd[sd < 1e-8] = 1.0

    def prep(d):
        X = d[feats].astype(float).values
        X = np.where(np.isnan(X), mu, X)         # impute with the TRAIN mean
        return ((X - mu) / sd).astype(np.float32)

    Xtr, Xcal, Xte = prep(tr), prep(cal), prep(te)
    Ytr, Mtr = build_target_and_mask(tr, config.HORIZONS_H)
    Ycal, Mcal = build_target_and_mask(cal, config.HORIZONS_H)
    log.info("supervision: train has %d valid (row,interval) terms out of %d possible "
             "(%.1f%% masked); mean K' per row = %.2f of %d",
             int(Mtr.sum()), Mtr.size, 100 * (1 - Mtr.mean()), float(Mtr.sum(axis=1).mean()), K)
    log.info("positives per interval (train): %s",
             {int(h): int(((Ytr[:, j] == 1) & (Mtr[:, j] == 1)).sum())
              for j, h in enumerate(config.HORIZONS_H)})

    models, val_losses = [], []
    for s in range(n_ensemble):
        seed = config.RANDOM_SEED + s
        log.info("training network %d/%d (seed=%d)…", s + 1, n_ensemble, seed)
        m, vl = train_one(Xtr, Ytr, Mtr, Xcal, Ycal, Mcal, seed, K, verbose=(n_ensemble == 1))
        models.append(m); val_losses.append(vl)
        log.info("  network %d done: best val masked-BCE = %.5f", s + 1, vl)

    def raw_hazards(X):
        """Ensemble mean hazard, plus the across-model std of the CUMULATIVE
        probability P(T<=c_j) (the paper's Section 5 uncertainty estimate).

        The std is taken on P, not on the raw hazard, because P is the quantity the
        alert threshold is applied to -- disagreement about a hazard deep in the
        curve matters only insofar as it moves P. Each member's own survival curve
        is reconstructed first, THEN the spread across members is measured.
        Returned so 19_ensemble_uncertainty.py can test whether that spread
        actually predicts error on THIS data rather than on turbofan engines.
        """
        stack = np.stack([predict_hazards(m, X) for m in models], axis=0)   # (m, n, K)
        p_stack = np.stack([1.0 - reconstruct_survival(stack[i])[:, 1:]
                            for i in range(stack.shape[0])], axis=0)        # (m, n, K)
        return stack.mean(axis=0), p_stack.std(axis=0)

    # per-interval isotonic calibration, identical to cells A and B
    raw_cal, _ = raw_hazards(Xcal)
    calibrators = {}
    for j, h in enumerate(config.HORIZONS_H):
        valid = Mcal[:, j] == 1
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(raw_cal[valid, j], Ycal[valid, j])
        calibrators[h] = iso
        log.info("interval j=%d (<=%2gh) calibrated on %d valid rows", j + 1, h, int(valid.sum()))

    def assemble(d, X, split_name):
        out = d[META].copy()
        out["split"] = split_name
        raw, p_std = raw_hazards(X)
        cal_h = np.clip(np.column_stack([calibrators[h].predict(raw[:, j])
                                         for j, h in enumerate(config.HORIZONS_H)]), 0.0, 1.0)
        S_raw, S_cal = reconstruct_survival(raw), reconstruct_survival(cal_h)
        assert (np.diff(S_cal, axis=1) <= 1e-9).all(), "S(c_j) is not non-increasing"
        for j, h in enumerate(config.HORIZONS_H):
            out[f"p_raw_{h}h"] = 1.0 - S_raw[:, j + 1]
            out[f"p_calibrated_{h}h"] = 1.0 - S_cal[:, j + 1]
            out[f"p_std_{h}h"] = p_std[:, j]   # across-member spread of P(T<=h)
        out["cond_time_24h"] = conditional_expected_time_24h(S_cal, cutpoints)
        out["ruler_time"] = news2_ruler_time(d)
        return out

    out_tr = assemble(tr, Xtr, "train")
    out_cal = assemble(cal, Xcal, "calib")
    out_te = assemble(te, Xte, "test")
    preds = pd.concat([out_tr, out_cal, out_te], ignore_index=True)
    preds.to_parquet(config.tpath(f"preds_mlp_ordinal{tag_suffix}.parquet"), index=False)

    c_tr = cindex(tr["T_hours"].values, 1.0 - out_tr["p_calibrated_24h"].values, tr["event"].values)
    c_te = cindex(te["T_hours"].values, 1.0 - out_te["p_calibrated_24h"].values, te["event"].values)
    ci_lo, ci_hi, nb = cluster_bootstrap_cindex_ci(
        te["T_hours"].values, 1.0 - out_te["p_calibrated_24h"].values,
        te["event"].values, te["subject_id"].values)
    log.info("C-index  MLP(m=%d)  train=%.4f test=%.4f  (95%% CI [%.4f, %.4f], n_boot=%d)",
             n_ensemble, c_tr, c_te, ci_lo, ci_hi, nb)
    if (c_tr - c_te) > 0.05:
        log.warning("*** train/test C-index gap %.4f > 0.05 -- possible overfit ***", c_tr - c_te)

    for i, m in enumerate(models):
        torch.save(m.state_dict(), os.path.join(model_dir, f"mlp_seed{i}.pt"))
    with open(os.path.join(model_dir, "calibrators.pkl"), "wb") as f:
        pickle.dump(calibrators, f)
    np.savez(os.path.join(model_dir, "scaler.npz"), mu=mu, sd=sd, features=np.array(feats))
    with open(os.path.join(model_dir, "meta.json"), "w") as f:
        json.dump(dict(
            architecture=f"shared-trunk MLP {list(HIDDEN)} + {K} hazard heads, masked BCE "
                         f"(Shroff arXiv:1903.09795 Eq 5), ensemble m={n_ensemble}",
            horizons=config.HORIZONS_H, features=feats, hidden=list(HIDDEN), dropout=DROPOUT,
            n_ensemble=n_ensemble, val_losses=val_losses,
            n_train_anchors=len(tr), n_calib_anchors=len(cal), n_test_anchors=len(te),
            pct_masked_terms=round(100 * (1 - float(Mtr.mean())), 2),
            mean_k_prime=round(float(Mtr.sum(axis=1).mean()), 3),
            c_index_train=float(c_tr), c_index_test=float(c_te),
            c_index_test_ci=[ci_lo, ci_hi], c_index_test_ci_n_boot=nb,
        ), f, indent=2)
    log.info("saved %d network(s) + calibrators + preds_mlp_ordinal%s.parquet (%d rows)",
             len(models), tag_suffix, len(preds))


# ══════════════════════════════════════════════════════════════════════════
def _selftest():
    """The mask must reproduce 12_ordinal_train's person-period inclusion set EXACTLY.

    If these two disagree, cells A/B and cell C are training on different data and
    the whole architecture comparison is meaningless -- so this is the single most
    important check in this file.
    """
    ok = True
    rng = np.random.default_rng(0)
    n = 4000
    df = pd.DataFrame(dict(
        T_hours=np.round(rng.uniform(0.5, 30, n), 2),
        event=rng.integers(0, 2, n),
        subject_id=np.arange(n), stay_id=np.arange(n),
    ))
    Y, M = build_target_and_mask(df, config.HORIZONS_H)

    pp = _t12.build_person_period_table(df, config.HORIZONS_H)
    dense_pp = np.zeros_like(M)
    lab_pp = np.zeros_like(Y)
    pos = {s: i for i, s in enumerate(df.stay_id.values)}
    for r in pp.itertuples():
        dense_pp[pos[r.stay_id], r.interval_j - 1] = 1.0
        lab_pp[pos[r.stay_id], r.interval_j - 1] = r.py_label

    if not np.array_equal(M, dense_pp):
        ok = False
        d = np.argwhere(M != dense_pp)[:5]
        print(f"  FAIL mask != person-period inclusion set, {len(np.argwhere(M != dense_pp))} "
              f"cells differ, e.g. {d.tolist()}")
    if not np.array_equal(Y * M, lab_pp * dense_pp):
        ok = False
        print("  FAIL labels differ from person-period py_label")

    # masking must be terminal: once masked, every later interval is masked too
    for i in range(n):
        row = M[i]
        if row.sum() and (nz := np.flatnonzero(row)).size:
            if nz.max() - nz.min() + 1 != nz.size:
                ok = False
                print(f"  FAIL row {i} has a hole in its interval coverage: {row}")
                break

    # masked_bce must equal a hand-computed value
    logits = torch.tensor([[0.0, 0.0, 0.0]], dtype=torch.float32)
    Yt = torch.tensor([[1.0, 0.0, 1.0]], dtype=torch.float32)
    Mt = torch.tensor([[1.0, 1.0, 0.0]], dtype=torch.float32)
    # sigmoid(0)=0.5 -> BCE = -log(0.5) = ln2 for every term; 2 unmasked terms,
    # K'=2, so the loss is exactly ln2 -- the third (masked) term must not count.
    got = float(masked_bce(logits, Yt, Mt))
    if abs(got - np.log(2)) > 1e-6:
        ok = False
        print(f"  FAIL masked_bce: got {got}, expected ln2={np.log(2):.6f}")

    # a fully-masked row must not produce NaN
    if not np.isfinite(float(masked_bce(logits, Yt, torch.zeros_like(Mt)))):
        ok = False
        print("  FAIL masked_bce on a fully-masked batch is not finite")

    print("SELFTEST", "PASS" if ok else "FAIL", "-- 17_mlp_ordinal_train.py")
    return ok


def sweep():
    """Small hyperparameter search, scored ONLY on calibration-split masked BCE.

    WHY THIS EXISTS. A first run early-stopped at epoch 9, which raises a fair
    objection: an under-trained MLP compared against a tuned XGBoost is a straw
    man, and a negative result from it would be worthless. This gives the MLP a
    genuine chance on a small, pre-declared grid.

    The selection metric is the SAME validation loss early stopping already uses,
    so no test data is touched at any point. The full grid is printed so the
    search is visible rather than implied.
    """
    df = pd.read_parquet(config.tpath("features.parquet"))
    feats = news2_feature_cols(df)
    tr_i, cal_i, _ = three_way_split(df)
    tr, cal = df.iloc[tr_i].copy(), df.iloc[cal_i].copy()
    Xtr_raw = tr[feats].astype(float).values
    mu, sd = np.nanmean(Xtr_raw, axis=0), np.nanstd(Xtr_raw, axis=0)
    sd[sd < 1e-8] = 1.0

    def prep(d):
        X = d[feats].astype(float).values
        return ((np.where(np.isnan(X), mu, X) - mu) / sd).astype(np.float32)

    Xtr, Xcal = prep(tr), prep(cal)
    Ytr, Mtr = build_target_and_mask(tr, config.HORIZONS_H)
    Ycal, Mcal = build_target_and_mask(cal, config.HORIZONS_H)
    K = len(config.HORIZONS_H)

    grid = [dict(hidden=h, lr=lr, dropout=dr)
            for h in ((128, 64), (256, 128))
            for lr in (3e-4, 1e-3)
            for dr in (0.1, 0.3)]
    results = []
    for cfg in grid:
        CFG.update(cfg); CFG["patience"] = 12; CFG["max_epochs"] = 80
        _, vl = train_one(Xtr, Ytr, Mtr, Xcal, Ycal, Mcal, config.RANDOM_SEED, K, verbose=False)
        results.append(dict(**cfg, val_masked_bce=vl))
        log.info("  hidden=%s lr=%.0e dropout=%.1f -> val masked-BCE %.6f",
                 cfg["hidden"], cfg["lr"], cfg["dropout"], vl)
    results.sort(key=lambda r: r["val_masked_bce"])
    best = results[0]
    log.info("BEST: hidden=%s lr=%.0e dropout=%.1f (val masked-BCE %.6f)",
             best["hidden"], best["lr"], best["dropout"], best["val_masked_bce"])
    with open(config.tpath("mlp_sweep.json").replace(".parquet", ""), "w") as f:
        json.dump(dict(grid=results, best=best,
                       selected_on="calibration-split masked BCE (no test data used)"), f, indent=2)
    return best


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sweep", action="store_true",
                    help="run the calibration-loss hyperparameter search and exit")
    ap.add_argument("--ensemble", type=int, default=1,
                    help="number of networks (different random init + shuffle). "
                         "m=6 reproduces the paper's Section 5 uncertainty ensemble.")
    ap.add_argument("--suffix", default="", help="output filename suffix, e.g. _m6")
    ap.add_argument("--lr", type=float, default=None)
    ap.add_argument("--hidden", default=None, help="comma-separated, e.g. 256,128")
    ap.add_argument("--dropout", type=float, default=None)
    ap.add_argument("--patience", type=int, default=None)
    ap.add_argument("--max-epochs", type=int, default=None)
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(0 if _selftest() else 1)
    if a.lr is not None:
        CFG["lr"] = a.lr
    if a.hidden:
        CFG["hidden"] = tuple(int(x) for x in a.hidden.split(","))
    if a.dropout is not None:
        CFG["dropout"] = a.dropout
    if a.patience is not None:
        CFG["patience"] = a.patience
    if a.max_epochs is not None:
        CFG["max_epochs"] = a.max_epochs
    if a.sweep:
        sweep()
    else:
        main(n_ensemble=a.ensemble, tag_suffix=a.suffix)
