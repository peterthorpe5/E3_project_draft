# Grant alignment

## What the supplied proposal commits to

The ARIA plant E3 proposal describes a comparative-genomics workflow using
DIAMOND2 and DeepClust to identify and cluster plant E3 proteins across a large
protein collection. It then combines expression and evolutionary evidence,
publishes a searchable database and prioritises ten broadly expressed clusters.
Milestone 1 is the plant E3 conservation/expression resource, with data and
database delivery during the first project year.

## How this package supports that commitment

| Proposal need | Benchmark contribution |
|---|---|
| DIAMOND2/DeepClust at plant-proteome scale | controlled full-input performance comparison |
| reproducible clustering | pinned versions, exact commands, checksums and atomic manifests |
| usable database-generation route | stage-specific time, memory and I/O evidence |
| scientifically stable candidate discovery | global membership and optional E3 sentinel guardrails |
| efficient delivery of Milestone 1 | predeclared 10% internal speed target on the costly pairwise stage |

The package is therefore grant-aligned enabling work. It improves the evidence
for choosing the computational route that produces the proposed E3 resource.

## Important qualification

The supplied proposal does not state an approximately 10% speed-improvement
target and does not list pairwise-method benchmarking as a formal deliverable.
Those are internal project-management requirements. They should be reported as
supporting optimisation, not quoted as language from the grant.

Likewise, a benchmark pass does not itself deliver the grant database or prove
that every member of an E3-seeded sequence cluster is an E3 ligase. The chosen
method must still feed the repository's discovery, evidence integration and
release workflow.
