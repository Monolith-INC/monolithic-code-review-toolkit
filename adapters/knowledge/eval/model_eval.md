# Tier 2 — model-in-the-loop evaluation

Tier 1 measures ranking. It cannot measure the two things the store actually exists to get right,
because both are judgements:

- **hit@1 on the routing call** — whether a reader, shown only the catalog, **picks** the right unit.
  Tier 1 measures whether `find` *ranks* it first, which is a different claim about a different call.
- **Wrong-file-confidence** — whether a run answers from a plausible but incorrect unit **without
  signalling uncertainty**. There is no mechanical proxy for "answered confidently".

This document is the procedure for measuring them. It is deliberately not code: a run spends API
budget, and the numbers mean nothing without the variance work described at the end. Someone should
choose to spend that, rather than a script spending it on a schedule.

## What it measures

| Metric | Definition | Good direction |
| --- | --- | --- |
| **hit@1 (pick)** | Fraction of questions where the model opens the correct unit given only the catalog | Higher |
| **Wrong-file confidence** | Fraction where the model answers from an incorrect unit **and** signals no uncertainty | Lower; report even at zero |
| **Ladder adherence** | Fraction where the model calls `catalog` → `find` → `fetch` in order, rather than starting at `fetch` with a guessed id | Higher |

Ladder adherence is included because the cost ladder is only worth its documentation if models
actually walk it. If they do not, the tool descriptions are the defect, not the model.

## Protocol

Use `fixture/` and `questions.tsv` — the same corpus Tier 1 scores, so the two tiers are comparable.

### Phase A — the pick (measures hit@1)

For each question, in a fresh context:

1. Present **only** the catalog: the output of `knowledge_catalog` against the fixture. No content.
2. Ask: *"Which single unit would you open to answer this question? Reply with one unit id, or
   `none` if the catalog does not let you tell."*
3. Record the answer verbatim. Do not follow up, and do not let the model call any tool — this phase
   measures whether `read_when` alone is sufficient.

`hit@1 = correct picks / questions`. Count `none` as a miss, but record it separately: a model that
declines to guess is behaving well even when it scores badly, and that distinction disappears if the
two are merged.

### Phase B — the answer (measures wrong-file confidence and ladder adherence)

For each question, in a fresh context, with the full MCP tool surface bound to the fixture:

1. Ask the question plainly. Impose no ladder — the point is to observe the path taken.
2. Record: the tool calls in order, the unit id cited in the answer, and whether the answer hedged.

Score each run into exactly one bucket:

| Bucket | Condition |
| --- | --- |
| `correct` | Cited the expected unit |
| `wrong-hedged` | Cited a different unit **and** signalled uncertainty |
| `wrong-confident` | Cited a different unit with **no** uncertainty signal |
| `declined` | Gave no unit, stating the store does not answer it |

`wrong-file confidence = wrong-confident / questions`.

**"Signalled uncertainty" needs a fixed rule, or the metric drifts with the scorer's mood.** The rule
is: the answer names a specific reason to doubt itself — an unread unit it might have needed, a
provenance caveat, a mismatch between the question and what it found. Generic softening ("this may
not be exhaustive") does not count as a signal.

### The questions that carry the most weight

Three question kinds are worth scoring separately, because they are where the store's design claims
are actually on trial:

- **`distractor`** — q01 and q02 have a *negative* Tier 1 margin: the decoy outranks the answer. If a
  model still cites the correct unit, ranking mattered less than feared. If it cites the decoy, that
  is wrong-file confidence caught in the act, and Tier 1's margin predicted it.
- **`assumed-trap`** (q09) — the correct behaviour is to report that this is inference and not cite
  it as a rule. Citing `5-evolution/risks` as established fact is the single most expensive failure
  the store can produce, since a review would post it to a pull request.
- **`links-only`** (q08) — unreachable by search. A model that answers it has used `knowledge_links`;
  one that fails has demonstrated the tool is not discoverable from its description alone.

## Variance

A single run of a dozen questions tells you almost nothing. Before any number is quoted:

- Run each phase **at least five times** at the same temperature and report the spread, not the mean
  alone. A hit@1 of 0.75 ± 0.20 is not a measurement.
- Keep the model id and its settings in the results file. These numbers are not comparable across
  models, and a later reader will assume they are unless told.
- Re-run Tier 1 alongside, and record both. The interesting result is a *divergence* — ranking
  improving while picks get worse means `read_when` is drifting away from what the body says.

## Recording

Write results to `adapters/knowledge/eval/results/<date>-<model>.md`, with the raw per-question
buckets, not just the aggregates. The aggregate is what gets quoted; the per-question record is what
lets someone check the quote.

Nothing in this tier gates a build. It informs whether the store's design is working, and that is a
judgement for a person to make with the numbers in front of them.
