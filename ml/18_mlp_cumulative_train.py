"""
Stage 18 — Cell D: the professor's paper's LITERAL parameterisation.

Cell C (17_mlp_ordinal_train.py) uses the same shared trunk but predicts
CONDITIONAL HAZARDS. This file predicts what the paper actually specifies —
the CUMULATIVE target of its Eq 2:

    y_j = 1  if the event has occurred by cutpoint c_j,  else 0

giving a non-decreasing target vector like [0, 0, 1, 1, 1, 1, 1].

WHY BUILD BOTH. "Why did you not follow the paper?" is a fair question, and the
honest answer needs a measurement, not an assertion. The two forms trade off:

  CUMULATIVE (this file)                   HAZARD (cell C)
  + far better class balance per head:     - every head fights a 2-4% positive
    the last head predicts "failed by        rate, because it only sees failures
    24h", ~22% positive, vs 4.4% for         inside its own interval
    the hazard head
  - monotonicity is NOT guaranteed. Two    + S(c_j) = S(c_{j-1})(1-h_j) is a
    independently calibrated heads can       running product of terms in [0,1],
    cross, giving P(T<=12h) > P(T<=24h),     so the curve can only fall.
    which is impossible. Needs a patch.      No patch, ever.

Two mitigations are applied here so the comparison is fair rather than a straw man:

  1. MONOTONE-BY-CONSTRUCTION HEADS. The raw network output is built as
         logit_1 = f_1(z)
         logit_j = logit_{j-1} + softplus(f_j(z))      for j > 1
     Since softplus > 0, the logits — and therefore the sigmoids — are
     non-decreasing in j. This is the neural analogue of the hazard model's
     running product, and it means the RAW curve needs no patch either.

  2. The patch is only needed AFTER per-interval isotonic calibration, because
     seven separately-fitted calibrators can still cross. `n_monotonicity_patched`
     in meta.json counts how often the cummax actually binds — that number IS the
     answer to "does the cumulative form need a patch?", measured rather than
     claimed.

Run: PYTHONUTF8=1 EWS_TAG=news2 py -3 18_mlp_cumulative_train.py
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
log = logging.getLogger("mlp_cumulative")

_t3 = importlib.import_module("03_train")
_t9 = importlib.import_module("09_focused_train")
_t12 = importlib.import_module("12_ordinal_train")
_t17 = importlib.import_module("17_mlp_ordinal_train")
three_way_split = _t3.three_way_split
news2_feature_cols, news2_ruler_time = _t9.news2_feature_cols, _t9.news2_ruler_time
conditional_expected_time_24h = _t12.conditional_expected_time_24h
cindex, cluster_bootstrap_cindex_ci = _t12.cindex, _t12.cluster_bootstrap_cindex_ci
masked_bce = _t17.masked_bce
META = _t17.META
HIDDEN, DROPOUT, LR, WEIGHT_DECAY = _t17.HIDDEN, _t17.DROPOUT, _t17.LR, _t17.WEIGHT_DECAY
BATCH, MAX_EPOCHS, PATIENCE = _t17.BATCH, _t17.MAX_EPOCHS, _t17.PATIENCE


def build_cumulative_target_and_mask(df: pd.DataFrame, horizons: list[float]):
    """The paper's Eq 2 + Eq 4, as dense (Y, M) matrices of shape (n, K).

    FAILED instance (event=1, time T):
        y_j = 1 for every c_j >= T, else 0.  All K sub-problems are known -> M=1
        everywhere, and K' = K (the paper's Eq 5 for a failed instance).

    CENSORED instance (event=0, last observed at T):
        we know it had NOT failed by any c_j <= T, so y_j = 0 there and M = 1.
        For c_j > T the outcome is genuinely unknown -> M = 0, and those units are
        dropped from the loss. This is exactly the paper's "target vector can only
        be partially obtained", with K' = (number of cutpoints at or below T).
    """
    T = df["T_hours"].to_numpy(dtype=float)
    E = df["event"].to_numpy().astype(bool)
    cuts = np.asarray([float(h) for h in horizons])[None, :]     # (1, K)
    Y = ((E[:, None]) & (T[:, None] <= cuts)).astype(np.float32)
    M = np.where(E[:, None], 1.0, (cuts <= T[:, None]).astype(np.float32)).astype(np.float32)
    return Y, M


class MonotoneCumulativeMLP(nn.Module):
    """Shared trunk + K heads whose outputs are non-decreasing in j BY CONSTRUCTION.

    head 1 is unconstrained; heads 2..K emit a softplus (strictly positive)
    increment that is added to the previous head's logit. The trunk is identical to
    cell C's, so the only difference under test is the target parameterisation.
    """

    def __init__(self, n_features: int, n_heads: int, hidden=HIDDEN, dropout=DROPOUT):
        super().__init__()
        layers, prev = [], n_features
        for h in hidden:
            layers += [nn.Linear(prev, h), nn.BatchNorm1d(h), nn.ReLU(), nn.Dropout(dropout)]
            prev = h
        self.trunk = nn.Sequential(*layers)
        self.heads = nn.ModuleList([nn.Linear(prev, 1) for _ in range(n_heads)])
        self.n_heads = n_heads

    def forward(self, x):
        z = self.trunk(x)
        cur = self.heads[0](z)
        outs = [cur]
        for j in range(1, self.n_heads):
            cur = cur + nn.functional.softplus(self.heads[j](z))
            outs.append(cur)
        return torch.cat(outs, dim=1)      # LOGITS, non-decreasing along dim 1


def train_one(Xtr, Ytr, Mtr, Xva, Yva, Mva, seed, n_heads, verbose=True):
    torch.manual_seed(seed); np.random.seed(seed)
    model = MonotoneCumulativeMLP(Xtr.shape[1], n_heads)
    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=3)
    Xtr_t, Ytr_t, Mtr_t = map(torch.from_numpy, (Xtr, Ytr, Mtr))
    Xva_t, Yva_t, Mva_t = map(torch.from_numpy, (Xva, Yva, Mva))
    n = len(Xtr_t); g = torch.Generator().manual_seed(seed)
    best, best_state, bad = float("inf"), None, 0
    for epoch in range(MAX_EPOCHS):
        model.train()
        perm = torch.randperm(n, generator=g)
        for i in range(0, n, BATCH):
            b = perm[i:i + BATCH]
            if len(b) < 2:
                continue
            opt.zero_grad()
            masked_bce(model(Xtr_t[b]), Ytr_t[b], Mtr_t[b]).backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(masked_bce(model(Xva_t), Yva_t, Mva_t))
        sched.step(vl)
        if vl < best - 1e-5:
            best, bad = vl, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
        if verbose and (epoch % 5 == 0 or bad >= PATIENCE):
            log.info("  seed=%d epoch %2d  val_loss=%.5f (best %.5f, bad %d)", seed, epoch, vl, best, bad)
        if bad >= PATIENCE:
            break
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model, best


def predict_cdf(model, X, batch=8192):
    out = []
    with torch.no_grad():
        for i in range(0, len(X), batch):
            out.append(torch.sigmoid(model(torch.from_numpy(X[i:i + batch]))).numpy())
    return np.vstack(out) if out else np.zeros((0, len(config.HORIZONS_H)))


def main(n_ensemble: int = 1, tag_suffix: str = ""):
    cutpoints = [0.0] + [float(h) for h in config.HORIZONS_H]
    K = len(config.HORIZONS_H)
    model_dir = config.tpath(f"models_mlp_cumulative{tag_suffix}")
    os.makedirs(model_dir, exist_ok=True)

    df = pd.read_parquet(config.tpath("features.parquet"))
    feats = news2_feature_cols(df)
    tr_i, cal_i, te_i = three_way_split(df)
    tr, cal, te = df.iloc[tr_i].copy(), df.iloc[cal_i].copy(), df.iloc[te_i].copy()
    log.info("split: train=%d calib=%d test=%d", len(tr), len(cal), len(te))

    Xtr_raw = tr[feats].astype(float).values
    mu, sd = np.nanmean(Xtr_raw, axis=0), np.nanstd(Xtr_raw, axis=0)
    sd[sd < 1e-8] = 1.0

    def prep(d):
        X = d[feats].astype(float).values
        return ((np.where(np.isnan(X), mu, X) - mu) / sd).astype(np.float32)

    Xtr, Xcal, Xte = prep(tr), prep(cal), prep(te)
    Ytr, Mtr = build_cumulative_target_and_mask(tr, config.HORIZONS_H)
    Ycal, Mcal = build_cumulative_target_and_mask(cal, config.HORIZONS_H)

    pos = {int(h): int(((Ytr[:, j] == 1) & (Mtr[:, j] == 1)).sum()) for j, h in enumerate(config.HORIZONS_H)}
    valid = {int(h): int(Mtr[:, j].sum()) for j, h in enumerate(config.HORIZONS_H)}
    log.info("CUMULATIVE positives per head (train): %s", pos)
    log.info("positive RATE per head: %s",
             {h: round(pos[h] / max(valid[h], 1), 4) for h in pos})
    log.info("  ^ compare cell C's hazard heads (2.4%%-4.4%%) -- this is the class-balance "
             "advantage of the cumulative form")

    models, val_losses = [], []
    for s in range(n_ensemble):
        seed = config.RANDOM_SEED + s
        log.info("training network %d/%d (seed=%d)…", s + 1, n_ensemble, seed)
        m, vl = train_one(Xtr, Ytr, Mtr, Xcal, Ycal, Mcal, seed, K, verbose=(n_ensemble == 1))
        models.append(m); val_losses.append(vl)
        log.info("  network %d done: best val masked-BCE = %.5f", s + 1, vl)

    def raw_cdf(X):
        stack = np.stack([predict_cdf(m, X) for m in models], axis=0)
        return stack.mean(axis=0), stack.std(axis=0)

    raw_cal, _ = raw_cdf(Xcal)
    calibrators = {}
    for j, h in enumerate(config.HORIZONS_H):
        v = Mcal[:, j] == 1
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        iso.fit(raw_cal[v, j], Ycal[v, j])
        calibrators[h] = iso

    patched_total = patched_rows = n_total = 0

    def assemble(d, X, split_name):
        nonlocal patched_total, patched_rows, n_total
        out = d[META].copy(); out["split"] = split_name
        raw, std = raw_cdf(X)
        assert (np.diff(raw, axis=1) >= -1e-6).all(), \
            "RAW cumulative output is not non-decreasing -- softplus construction is broken"
        F = np.clip(np.column_stack([calibrators[h].predict(raw[:, j])
                                     for j, h in enumerate(config.HORIZONS_H)]), 0.0, 1.0)
        # THE PATCH the hazard form never needs: seven independently fitted
        # isotonic calibrators can cross, producing P(T<=12h) > P(T<=24h).
        viol = (np.diff(F, axis=1) < -1e-9)
        patched_total += int(viol.sum()); patched_rows += int(viol.any(axis=1).sum()); n_total += len(F)
        F = np.maximum.accumulate(F, axis=1)
        assert (np.diff(F, axis=1) >= -1e-9).all()
        for j, h in enumerate(config.HORIZONS_H):
            out[f"p_raw_{h}h"] = raw[:, j]
            out[f"p_calibrated_{h}h"] = F[:, j]
            out[f"hazard_std_{h}h"] = std[:, j]
        out["cond_time_24h"] = conditional_expected_time_24h(1.0 - np.column_stack(
            [np.zeros(len(F)), F]), cutpoints)
        out["ruler_time"] = news2_ruler_time(d)
        return out

    out_tr, out_cal, out_te = assemble(tr, Xtr, "train"), assemble(cal, Xcal, "calib"), assemble(te, Xte, "test")
    preds = pd.concat([out_tr, out_cal, out_te], ignore_index=True)
    preds.to_parquet(config.tpath(f"preds_mlp_cumulative{tag_suffix}.parquet"), index=False)

    log.info("MONOTONICITY PATCH: %d of %d predictions (%.3f%%) needed a cummax after "
             "calibration, touching %d cell(s). The hazard form (cell C) needed 0.",
             patched_rows, n_total, 100 * patched_rows / max(n_total, 1), patched_total)

    c_tr = cindex(tr["T_hours"].values, 1.0 - out_tr["p_calibrated_24h"].values, tr["event"].values)
    c_te = cindex(te["T_hours"].values, 1.0 - out_te["p_calibrated_24h"].values, te["event"].values)
    ci_lo, ci_hi, nb = cluster_bootstrap_cindex_ci(
        te["T_hours"].values, 1.0 - out_te["p_calibrated_24h"].values,
        te["event"].values, te["subject_id"].values)
    log.info("C-index  MLP-CUMULATIVE  train=%.4f test=%.4f  (95%% CI [%.4f, %.4f])",
             c_tr, c_te, ci_lo, ci_hi)

    for i, m in enumerate(models):
        torch.save(m.state_dict(), os.path.join(model_dir, f"mlp_cum_seed{i}.pt"))
    with open(os.path.join(model_dir, "calibrators.pkl"), "wb") as f:
        pickle.dump(calibrators, f)
    np.savez(os.path.join(model_dir, "scaler.npz"), mu=mu, sd=sd, features=np.array(feats))
    with open(os.path.join(model_dir, "meta.json"), "w") as f:
        json.dump(dict(
            architecture=f"shared-trunk MLP {list(HIDDEN)} + {K} MONOTONE cumulative heads "
                         f"(Shroff arXiv:1903.09795 Eq 2 target, Eq 5 masked loss), m={n_ensemble}",
            horizons=config.HORIZONS_H, n_ensemble=n_ensemble, val_losses=val_losses,
            positives_per_head=pos,
            positive_rate_per_head={str(h): round(pos[h] / max(valid[h], 1), 4) for h in pos},
            n_monotonicity_patched_rows=patched_rows, n_monotonicity_patched_cells=patched_total,
            pct_rows_patched=round(100 * patched_rows / max(n_total, 1), 4),
            c_index_train=float(c_tr), c_index_test=float(c_te), c_index_test_ci=[ci_lo, ci_hi],
        ), f, indent=2)
    log.info("saved preds_mlp_cumulative%s.parquet (%d rows)", tag_suffix, len(preds))


def _selftest():
    ok = True
    df = pd.DataFrame(dict(T_hours=[5.0, 13.0, 30.0, 5.0, 13.0],
                           event=[1, 1, 1, 0, 0]))
    Y, M = build_cumulative_target_and_mask(df, config.HORIZONS_H)   # cuts 2,4,6,9,12,18,24
    exp_Y = np.array([
        [0, 0, 1, 1, 1, 1, 1],      # fails at 5h  -> 1 from the 6h cutpoint on
        [0, 0, 0, 0, 0, 1, 1],      # fails at 13h -> 1 from the 18h cutpoint on
        [0, 0, 0, 0, 0, 0, 0],      # fails at 30h -> beyond every cutpoint
        [0, 0, 0, 0, 0, 0, 0],      # censored at 5h
        [0, 0, 0, 0, 0, 0, 0],      # censored at 13h
    ], dtype=np.float32)
    exp_M = np.array([
        [1, 1, 1, 1, 1, 1, 1],      # failed -> all K known (paper: K'=K)
        [1, 1, 1, 1, 1, 1, 1],
        [1, 1, 1, 1, 1, 1, 1],
        [1, 1, 0, 0, 0, 0, 0],      # censored at 5h -> known only for c_j<=5 (2h,4h)
        [1, 1, 1, 1, 1, 0, 0],      # censored at 13h -> known for c_j<=13 (2..12h)
    ], dtype=np.float32)
    if not np.array_equal(Y, exp_Y):
        ok = False; print(f"  FAIL cumulative Y:\n{Y}\nexpected\n{exp_Y}")
    if not np.array_equal(M, exp_M):
        ok = False; print(f"  FAIL cumulative M:\n{M}\nexpected\n{exp_M}")
    if not (np.diff(Y, axis=1) >= 0).all():
        ok = False; print("  FAIL cumulative target must be non-decreasing")

    # monotone head construction
    torch.manual_seed(0)
    net = MonotoneCumulativeMLP(8, 7); net.eval()
    with torch.no_grad():
        out = net(torch.randn(64, 8))
    if not bool((out[:, 1:] - out[:, :-1] >= -1e-6).all()):
        ok = False; print("  FAIL monotone heads emitted a decreasing logit sequence")
    print("SELFTEST", "PASS" if ok else "FAIL", "-- 18_mlp_cumulative_train.py")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ensemble", type=int, default=1)
    ap.add_argument("--suffix", default="")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(0 if _selftest() else 1)
    main(n_ensemble=a.ensemble, tag_suffix=a.suffix)
