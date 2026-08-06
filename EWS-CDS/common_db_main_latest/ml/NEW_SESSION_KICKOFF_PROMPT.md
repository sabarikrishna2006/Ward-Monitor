# Kickoff Prompt — paste this verbatim as the first message of the new session

---

I'm continuing work on the EWS deterioration-model project (`E:\IP_EarlyWarning\EWS-CDS\common_db_main_latest\ml\`). Two prior sessions already did substantial work here. Before you say anything else, do this:

## Step 1 — Load context, in this exact order, fully, before responding

1. `E:\IP_EarlyWarning\EWS-CDS\common_db_main_latest\ml\SESSION_HANDOFF_ordinal_model_v1.md`
   — written 2026-07-27, the most current. Every number here is authoritative.
2. `E:\IP_EarlyWarning\EWS-CDS\common_db_main_latest\ml\ANTIGRAVITY_PROJECT_CONTEXT.md`
   — written 2026-07-23 by a different session. Deeper on mechanics (§9's exact code-level
   walkthrough of the person-period/masking logic, `_confusion_at`, `alarm_episode_metrics`)
   and has a large anticipated-question FAQ (§10) worth absorbing for defending this live.
   **It is stale on headline numbers** (256,712 rows/7,724 stays vs. file 1's 298,679/9,157) —
   wherever the two disagree, file 1 wins. If you're ever unsure, recompute from
   `data/metrics_focused.json` directly rather than trusting either file's prose.
3. Memory (should auto-load in this project; if it doesn't, ask me): `project_ews_survival_model.md`,
   `project_ews_label_circularity.md`.

Do not re-explore the codebase, re-derive the pipeline, or re-run anything to "confirm" these
files are right, unless a specific number you're about to use seems inconsistent between
sources — in that case, recompute it from `data/metrics_focused.json` yourself and tell me
which file was wrong.

## Step 2 — Do not proceed to any plan or code until you've done this

**I have feedback from my professor on this model that neither file above contains — I'm
about to paste it below (or if I haven't yet, ask me for it explicitly before doing anything
else).** Do not guess what the feedback probably is from the FAQ sections above and start
building against your guess. Wait for the actual points, then:

1. Restate each point back to me in your own words, mapped to the specific number/plot/design
   decision in the codebase it touches — so I can confirm you understood it correctly before
   any work starts.
2. Tell me, for each point, whether it's asking for (a) a new analysis/number we don't have,
   (b) a genuine model change, (c) a presentation/explanation fix, or (d) something the
   project's own history already answered (check §6/§7/§10 of file 2 and §7/§9 of file 1
   before assuming it's new — but if it genuinely is new, say so, don't force-fit it into an
   old answer).

## Step 3 — The standing rules for this whole session (non-negotiable)

**Verify, don't assume.** Every number you tell me must trace to `data/metrics_focused.json`,
`data/stage0_verification_news2.json`, or a script you actually ran this session — never to
"I recall this was..." from the handoff files alone if it's about to become something I say
out loud to my professor. The handoff files are a starting point for orientation, not a
citation source for the final deliverable.

**Do not be a yes-man.** If I propose an approach, a metric, a framing, or a fix and it's
weak, wrong, circular, or has already been tried and failed (check the handoff files — labs
retrain was a null result, the AFT-vs-hazard framing switch barely moved discrimination, Cox
is predicted to land in the same 0.79 AUC range) — **say so directly and explain why**, don't
soften it into agreement. I would rather be told "that won't work, here's why" three times
than be told "great idea" once and find out in front of my professor that it wasn't. If you
disagree with a direction I want to take, argue the disagreement explicitly before doing the
work, not after.

**Bring actual critical thinking, not a checklist.** This project has already been through one
round of "the model looks fine because the AUC is high" that fell apart under real questions.
Don't propose the first standard textbook answer (add more features, try a fancier model,
tune the threshold) without first asking whether it's likely to move the *actual* bottleneck —
the honest finding from this project so far is that the ceiling here is probably a
label/feature information-content limit, not a model-family or feature-richness limit (two
independent negative results already confirm this: labs didn't help, framing switch barely
helped). Any improvement idea should engage with *why* that ceiling exists, not just throw
another standard technique at it. If a genuinely different angle exists — e.g. the
already-flagged-but-unbuilt idea of directly regresseing the future NEWS2 value/band instead
of a threshold-crossing time-to-event (file 2, §6, last bullet) — take it seriously and reason
through it with me rather than defaulting to "let's just add Cox" or "let's just tune
hyperparameters."

**Explain as you go, so I can defend it myself.** Every plot, every metric, every design
decision needs to be something I can explain in my own words afterward, unprompted, under
questioning. Don't just produce a result — walk me through the definition, the computation,
and the interpretation before it becomes something I'd present. This is not optional politeness,
it's the actual goal: I need to walk in tomorrow sounding like I understand this model deeply
and made deliberate choices, not like I ran a pipeline someone else built for me. If you notice
me nodding along without being able to restate something back to you, stop and check I actually
absorbed it before moving on.

**Professional quality, presentation-ready, but never oversold.** Numbers that are weak (the
point-time correlation, the 54.3% residual coverage gap, the null labs result) get stated as
weak, with the honest reason why, not spun. A defensible "this doesn't work and here's why" is
worth more to me right now than a polished number I can't explain if pushed.

## Step 4 — Then, and only then

Once you've confirmed you understand my professor's actual feedback and I've corrected any
misreading, propose a plan (use plan mode / ask clarifying questions if the right approach
genuinely isn't obvious — don't silently pick one and run). I'd rather spend a few extra
minutes agreeing on the right direction than have you build the wrong thing well.
