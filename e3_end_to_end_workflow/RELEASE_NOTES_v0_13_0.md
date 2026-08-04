# e3_end_to_end_workflow v0.13.0

Version 0.13.0 consumes the corrected Expression Atlas v0.5.0 data contract.

- uses median expression for Atlas five-number contexts;
- applies the inclusive `>= 0.5` expression boundary;
- prefers TPM per species/experiment and records FPKM fallback;
- retains candidate-by-context tissue, stage, treatment and condition output;
- separates `NOT_MAPPED`, `NO_EXPRESSION_RECORDS` and measured low/zero states;
- rejects missing/duplicate metadata contexts and stale expression/metadata
  checksum bindings;
- restricts domain assessed/supported species to configured target species;
- adds known-answer, corruption, boundary and off-target-denominator tests.

Validation: 224 tests passed, one optional environment test skipped, with
90.56% branch-aware coverage.
