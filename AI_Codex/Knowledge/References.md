---
title: References
type: knowledge
tags:
  - code-review
  - plugin-research
  - references
created: 2026-08-27
---

# References

This note records local plugin sources examined for ideas that may improve the Monolithic Code Review Toolkit. Each entry is added only after its source has been read.

## Lookup progress

- [x] `cursor-team-kit/skills/thermo-nuclear-code-quality-review`
- [x] `cursor-team-kit/skills/make-pr-easy-to-review`
- [x] `pr-review-canvas`
- [x] `ralph-loop`
- [x] `cursor-team-kit/skills/verify-this`
- [x] `pstack/skills/typescript-best-practices`

## Sources

### Thermo-Nuclear Code Quality Review

Source: `plugins/cursor-team-kit/skills/thermo-nuclear-code-quality-review/SKILL.md`

A deliberately strict maintainability-review rubric. Its most useful idea is to rank structural regressions above cosmetic feedback and actively search for a restructuring that deletes branches, wrappers, modes, or layers while preserving behavior. It also supplies concrete checks for boundary leakage, weak type contracts, misplaced ownership, non-atomic state changes, and unnecessary sequential orchestration. Its fixed 1,000-line threshold is best treated as a review trigger that asks for justification, not as a universal quality rule.

### Make PR Easy to Review

Source: `plugins/cursor-team-kit/skills/make-pr-easy-to-review/SKILL.md`

A workflow for reducing reviewer effort without changing behavior. It inventories commit noise, unrelated or generated files, mixed mechanical and logical changes, stale descriptions, risk, and test evidence; then offers reviewer entry points and dependency-ordered commits. History rewriting requires an approved plan and a before-and-after Git tree identity check. This is valuable as a preparation stage adjacent to review, but it should remain distinct from finding correctness or maintainability defects.

### PR Review Canvas

Sources: `plugins/pr-review-canvas/skills/pr-review-canvas/SKILL.md`, `plugins/pr-review-canvas/README.md`, and `plugins/pr-review-canvas/CHANGELOG.md`

A reviewer-comprehension model that orders a change set by attention value instead of file-tree order: core behavior first, wiring second, and mechanical changes last. Dense logic may gain pseudocode; surprising behavior may gain a concrete old-versus-new execution trace; risky hunks may gain sparse, labeled callouts. The Canvas rendering is product-specific, but the information architecture transfers to Markdown reports. The skill and README disagree about whether local diffs are accepted, illustrating why published capability claims should be checked against executable skill contracts.

### Ralph Loop

Fontes: `plugins/ralph-loop/README.md`, `plugins/ralph-loop/skills/ralph-loop/SKILL.md`, `plugins/ralph-loop/hooks/hooks.json`, `plugins/ralph-loop/hooks/capture-response.sh` e `plugins/ralph-loop/hooks/stop-hook.sh`

Padrão de iteração orientado a hooks e recuperável (estado persistido no repositório). Verifica um marcador exato de conclusão após cada resposta, reemite o prompt inalterado ao fim do turno, aplica um teto opcional de iterações e interrompe com segurança quando o estado é inválido. O padrão pode sustentar ciclos limitados de revisão ou remediação com checkpoints explícitos. O marcador de conclusão é apenas uma autoafirmação, então um toolkit de review deve exigir evidência objetiva de gate antes de considerar um ciclo concluído.

### Verify This

Source: `plugins/cursor-team-kit/skills/verify-this/SKILL.md`

A claim-verification protocol that turns a statement into a falsifiable condition, metric, and threshold; captures baseline and treatment with the same command, data, and environment; compares raw artifacts; and returns one of three explicit verdicts: `VERIFIED`, `NOT VERIFIED`, or `INCONCLUSIVE`. It distinguishes passing tests from evidence that a user-visible, performance, or resource claim is true. The explicit inconclusive state prevents weak or incomparable evidence from being presented as confirmation.

### TypeScript Best Practices

Sources: `plugins/pstack/skills/typescript-best-practices/SKILL.md`, `plugins/pstack/skills/typescript-best-practices/references/patterns.md`, `plugins/pstack/skills/principle-type-system-discipline/SKILL.md`, and `plugins/pstack/skills/principle-boundary-discipline/SKILL.md`

A language-specific review pack grounded in broader type-system and boundary principles. It recommends discriminated unions, semantic primitive brands, exhaustive matching, validation of unknown data at system boundaries, schema-derived types, honest narrowing, total function signatures, real tests, and structured telemetry. These checks fit an optional, language-aware review layer rather than the toolkit's universal core. One supplied example is unsound: `{ start, durationMs: number }` still admits a negative duration, so it does not make invalid ranges unconstructable without a validated duration type.
