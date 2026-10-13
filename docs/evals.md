# Eval results

Every prompt change is measured on the same fixed sample before it is accepted.

## Triage

**How to run:** `uv run python -m maintainer_copilot.eval_triage`
(raw per-issue results are written to `data/eval/`, which is not committed).

**Sample:** 10 closed `pydantic/pydantic` issues chosen by `ORDER BY md5(number)`, so every run
uses the same issues: #12223, #12558, #12962, #12362, #12771, #12514, #13104, #12822, #13834, #13342.
Excluded: the few-shot example issues (#12393, #12044) and the issue used while writing the
prompt (#13868), because testing on them would flatter the results.

**Metrics**

- Schema failures: the model's output could not be parsed into `TriageResult`.
- Evidence verified: `evidence_quote` appears word for word in the issue (whitespace ignored).
- Labels dropped: labels the model invented that are not in the repository's label list.
- Shares a label with maintainers: at least one suggested label matches a label the maintainers
  actually applied. Counted only over issues that have maintainer labels.

### Results

| Date | Prompt | Model | Schema failures | Evidence verified | Labels dropped | Shares a label | Time |
|---|---|---|---|---|---|---|---|
| 2026-10-13 | triage.v1, no examples, no label list (smoke test, 1 issue × 4 runs) | qwen2.5:3b | 2/4 | not checked | not checked | 0/4 | — |
| 2026-10-13 | triage.v1 + 2 examples | qwen2.5:3b | **0/10** | **7/10** | 0 | **5/8** | 57 s |

### triage.v1: weaknesses found

1. **`bug V1` vs `bug V2`.** #13104 and #13834 were labelled `bug V1` although both reporters run
   pydantic 2.x. The prompt never says how to tell the two apart.
2. **Maintainer-only labels.** #13342 got `needs-blogpost-entry`, a release-process label. It is in
   the allowlist, so validation can't catch it; the allowlist should exclude process labels.
3. **Wrong kind.** #12362 was classified as `question`; maintainers labelled it `bug V2`.
4. **Altered quotes (3/10).** #12558 swapped `@` for the full-width `＠`; #13104 and #13834 paraphrased.
   All three were caught and blanked by the evidence check.

### Ideas for triage.v2

- State the rule: pydantic version 2.x → `bug V2`, 1.x → `bug V1`.
- Pass only triage labels (`bug *`, `feature request`, `question`, `documentation`, `topic-*`)
  instead of all 58.
- Add a third few-shot example of a bug report that sounds like a question.
- Keep the evidence check strict; re-measure whether the new examples reduce altered quotes.
