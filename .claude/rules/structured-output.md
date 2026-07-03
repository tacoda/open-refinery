# Structured output

Any model response or output that gets **persisted** must be structured when it
can be — prefer a schema (JSON) over free text.

- If a step's output has a shape (a security review, a triage verdict, an eval
  result, extracted fields), define that shape and store it structured, not as a
  prose blob. Example: a security-reviewer agent returns
  `{"passed": bool, "findings": [...], "severity": "..."}`, not a paragraph.
- Executor backends should request/enforce structured output from the model
  (tool/JSON mode) whenever the result is machine-consumed or audited.
- Store the structured value (JSON column / typed field), so it's queryable,
  attestable, and diffable — not re-parsed from text later.
- Free text is the fallback only when the output genuinely has no structure.

Structured output makes results verifiable and auditable — the point of the
open factory.
