"""Transparent ranking formulas and a non-authoritative weight explorer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Real

import pandas as pd

DEFAULT_RANKING_WEIGHTS: dict[str, dict[str, float]] = {
    "prestructure": {
        "discovery": 0.10,
        "orthology": 0.35,
        "domain": 0.20,
        "expression": 0.35,
    },
    "ligandability": {
        "minimum_druggability": 0.25,
        "pocket_plddt": 0.25,
        "member_mapping": 0.25,
        "predictor_agreement": 0.25,
    },
    "structural": {
        "ligandability": 0.55,
        "pocket_conservation": 0.45,
    },
    "final": {
        "prestructure": 0.60,
        "structural": 0.40,
    },
}

RANKING_WEIGHT_LABELS: dict[str, dict[str, str]] = {
    "prestructure": {
        "discovery": "Discovery score",
        "orthology": "Orthology score",
        "domain": "Domain score",
        "expression": "Expression score",
    },
    "ligandability": {
        "minimum_druggability": "Minimum member druggability",
        "pocket_plddt": "Mean pocket pLDDT fraction",
        "member_mapping": "All-member mapping pass",
        "predictor_agreement": "Pocket-predictor agreement",
    },
    "structural": {
        "ligandability": "Ligandability score",
        "pocket_conservation": "Pocket-conservation score",
    },
    "final": {
        "prestructure": "Pre-structure score",
        "structural": "Structural score",
    },
}

RANKING_METHODOLOGY_MARKDOWN = r"""
### How the recorded computational ranking was calculated

The authoritative candidate list is a **deterministic prioritisation of the
computational evidence collected by the workflow**. It is not a predicted
probability that a protein is an E3 ubiquitin ligase, a probability that a
protein contains a genuinely ligandable pocket, or a prediction that a PROTAC
directed against that protein will work experimentally.

The purpose of the ranking is narrower and more transparent: to place
candidates with the strongest combined discovery, evolutionary, domain,
expression, pocket and structural evidence near the top of the list, while
retaining the individual evidence components from which that ordering was
derived.

Three kinds of information are deliberately kept separate:

1. **Hard grant-aligned gates**, which record whether a candidate satisfies a
   mandatory requirement.
2. **Continuous evidence scores**, which distinguish stronger and weaker
   evidence among otherwise comparable candidates.
3. **Evidence-availability and completeness fields**, which show whether each
   component could actually be assessed.

This separation is important. A large continuous score cannot compensate for
failure of a mandatory gate. For example, unusually strong expression or
orthology evidence cannot repair failure of an all-members druggability rule.
Likewise, unavailable evidence is not silently treated as evidence of failure
or success: missingness, assessment status and gate outcome remain explicit in
the authoritative results.

Unless otherwise stated, component scores range from zero to one. Values nearer
one represent stronger support and values nearer zero represent weaker support.
A value of 0.5 may be used as a neutral numerical contribution when a component
has no assessable denominator, but this **does not mean that the underlying
biological criterion passed**. The equations are reproducible evidence
summaries, not calibrated biological probabilities.

#### 1. Discovery score

For the lead DeepClust cluster, the discovery score was:

$$
D=\frac{f_{reviewed}+f_{ubiquitin\ GO}+(1-f_{exclusion})}{3}
$$

where:

- $f_{reviewed}$ is the fraction of relevant seed proteins derived from
  reviewed protein records;
- $f_{ubiquitin\ GO}$ is the fraction of relevant seeds with ubiquitin-related
  Gene Ontology evidence; and
- $f_{exclusion}$ is the fraction of relevant seeds carrying an exclusion flag.

The term $1-f_{exclusion}$ converts the exclusion fraction into a positive
support term. A cluster with no exclusion-flagged seeds receives one for this
component; a cluster in which every relevant seed is exclusion-flagged receives
zero. The three terms contribute equally.

The discovery score therefore rewards support from reviewed records,
ubiquitin-related functional annotation and absence of evidence that the
cluster belongs to an excluded or unsuitable category. It does not independently
establish that every cluster member is an E3 ligase. It summarises how strongly
the original discovery evidence resembles that expected for the target protein
class. Where several sequence clusters were associated with the same broader
evolutionary group, the deterministically selected lead cluster represented the
discovery evidence in the consolidated ranking.

#### 2. Orthology score

The orthology score was:

$$
O=f_{target}(0.8+0.2f_{mandatory})
$$

where $f_{target}$ is the fraction of all target species represented in the
evolutionary group and $f_{mandatory}$ is the fraction of the six mandatory crop
species represented.

The principal contribution comes from $f_{target}$. Broad representation across
the complete target panel supplies most of the score, while the mandatory-species
term modifies that broad representation by a factor between 0.8 and 1.0. Thus:

- if all target species and all mandatory species are represented, $O=1$;
- if all target species are represented but the mandatory-species contribution
  is absent, the maximum is $O=0.8$; and
- if only half of the target species are represented, $O$ cannot exceed 0.5,
  even when all mandatory species are present.

This prioritises broadly conserved evolutionary groups while retaining a
smaller explicit adjustment for the grant-critical crop species. It does not
state that all orthologues have identical biochemical functions or the same
ligand-binding cavity. Mandatory-species representation also remains an
explicit evidence field and gate, so a strong continuous orthology score cannot
conceal failure of a separately required condition.

#### 3. Domain and expression scores

**Domain score**

$$
A=\frac{\text{domain-assessed species with an E3-associated domain}}
        {\text{species for which domain evidence was assessable}}
$$

The numerator counts domain-assessed species in which at least one domain from
the project's catalogue of E3-associated domains was detected. The denominator
contains only species for which the required domain assessment was available.
Consequently, $A=1$ means that every assessed species supported a catalogued
E3-associated domain, $A=0.5$ means that half did so, and $A=0$ means that none
did.

This is a cross-species consistency measure rather than a check of a single
representative protein. It depends on the defined project catalogue and the
available annotation. Failure to detect a catalogued domain is not necessarily
proof that the protein lacks E3 function, particularly for divergent,
incomplete or poorly annotated proteins. Assessed counts, availability and gate
status are therefore retained separately.

**Expression score**

$$
E=\frac{\text{uniquely mapped, expression-assessed species with broad support}}
        {\text{uniquely mapped species for which expression was assessable}}
$$

The calculation is restricted to species whose expression evidence could be
mapped uniquely to the relevant candidate. This prevents ambiguous expression
assignments from being counted as if they belonged confidently to one protein
or evolutionary group.

A high value means that broad expression support was observed consistently
across species with uniquely mapped, assessable evidence. It does not mean that
every species in the evolutionary group had expression data, or that expression
was equally strong in every tissue, condition or developmental stage.
Availability, unique-mapping status and the expression gate remain separate, so
the results distinguish unavailable data, ambiguous mapping and assessed
evidence that did not meet the expression criterion.

**Treatment of an unavailable denominator**

When no valid assessed denominator was available for the domain or expression
component, the integrated calculation used the neutral value 0.5. This avoids
giving missing evidence the maximum value of one while also avoiding treating
the absence of an assessable dataset as direct biological evidence against the
candidate.

The neutral value does not erase missingness. The workflow retains the assessed
count, eligible denominator, evidence-availability state, mapping status, gate
outcome and overall evidence-completeness value. A candidate with a genuine
intermediate score can therefore still be distinguished from one assigned 0.5
because the component was unavailable. Evidence completeness is also available
as a later deterministic tie-break.

#### 4. Pre-structure score

The four pre-structure components were integrated as:

$$
P=0.10D+0.35O+0.20A+0.35E
$$

The weights sum to one and reflect the intended prioritisation:

- **10% discovery evidence:** confidence in the original sequence-cluster
  discovery signal;
- **35% orthology evidence:** breadth of evolutionary representation across the
  target species;
- **20% domain evidence:** consistency of catalogued E3-associated domain
  support; and
- **35% expression evidence:** breadth of uniquely mapped expression support.

Orthology and expression receive the largest weights because the grant-aligned
objective required candidates that were broadly represented and supported by
expression evidence. Domain evidence provides an important but smaller
functional contribution. Discovery evidence is retained at a lower weight
because it describes how the candidate entered the analysis and should not
dominate later evolutionary and biological evidence.

$P$ records the strength of evidence available before ligandability,
pocket-conservation and three-dimensional analyses are incorporated. It is a
ranking component, not an independent pass/fail decision. The corresponding
hard gates remain separate.

#### 5. Ligandability score

The ligandability score combined four equally weighted properties of the
selected pocket:

$$
L=\frac{d_{min}+p_{pLDDT}+m_{map}+p_{agree}}{4}
$$

where:

- $d_{min}$ is the minimum selected-pocket druggability across assessed members;
- $p_{pLDDT}$ is the mean normalised pocket-confidence support;
- $m_{map}$ is an all-members pocket-mapping indicator; and
- $p_{agree}$ is the fraction of assessed members supported by both recorded
  pocket-ranking signals.

**Minimum druggability.** The minimum, rather than the mean or maximum, makes
$d_{min}$ deliberately conservative. It prevents a high average from concealing
one poorly supported member and asks whether druggability is maintained across
the assessed group. This continuous term complements but does not replace the
hard all-members druggability rule. Failure of that mandatory rule cannot be
repaired by the other ligandability components.

**Pocket confidence.** $p_{pLDDT}$ summarises confidence in the predicted
structural regions contributing to the pockets. Higher support means that the
pocket residues are located in more confidently modelled regions. This is
confidence in the predicted local structure, not experimental confirmation of a
cavity, ligand binding or conformational stability.

**All-members mapping.** The mapping term is deliberately binary:

$$
m_{map}=\begin{cases}
1, & \text{if every assessed member passes pocket mapping}\\
0, & \text{otherwise.}
\end{cases}
$$

It records whether the selected pockets and their lining residues could be
reconciled to the corresponding full protein models for every assessed member.
A single mapping failure removes this component, although it does not set the
entire ligandability score to zero. Any mandatory mapping gate is applied
separately.

**Agreement between pocket-ranking signals.** $p_{agree}$ is the fraction of
assessed members for which the selected FPocket pocket was also supported by the
P2Rank rescoring result. P2Rank 2.5.1 was used in `fpocket-rescore` mode with the
`rescore_2024` model. It did not define a second independent cavity set; it
rescored and reordered the FPocket pockets. Agreement therefore means support
from both the original FPocket assessment and the P2Rank-derived ranking of
those same cavities, not agreement between two independent pocket-discovery
experiments.

$L$ summarises whether the selected cavity is consistently druggable,
structurally credible, successfully mapped and supported by the two recorded
ranking signals. It remains computational ligandability evidence rather than
proof that a suitable chemical ligand exists.

#### 6. Pocket-conservation score

The stored pocket-conservation score was:

$$
C=0.30f_{component}+0.25o_{region}+0.20c_{chemical}
  +0.15d_{min}+0.10p_{pLDDT}
$$

where:

- $f_{component}$ is conserved-component coverage;
- $o_{region}$ is mean aligned pocket-region overlap;
- $c_{chemical}$ is biochemical-class conservation;
- $d_{min}$ is minimum selected-pocket druggability; and
- $p_{pLDDT}$ is mean normalised pocket-confidence support.

**Conserved-component coverage (30%).** This records how completely the relevant
conserved pocket component is represented across assessed members. It rewards a
broadly conserved and consistently traceable component rather than a signal
present in only a small subset.

**Aligned pocket-region overlap (25%).** This measures overlap of the mapped
pocket regions after sequence alignment. It asks whether residues associated
with the selected reference pocket correspond to the same aligned sequence
region in other members. It is more focused than whole-protein similarity, but
sequence-region overlap does not prove that the residues occupy an equivalent
three-dimensional arrangement.

**Biochemical-class conservation (20%).** This asks whether the biochemical
character of pocket-lining residues is conserved. Conservative substitutions
can retain support when chemically similar residues replace one another. This
is a simplified representation of chemical similarity and does not model every
effect of side-chain geometry, protonation, solvent exposure or conformation.

**Druggability and confidence (25% combined).** Minimum druggability contributes
15% and mean pocket pLDDT contributes 10%. Including them prevents a highly
conserved sequence region associated with a consistently weak or poorly
predicted cavity from receiving an inappropriately strong score.

$C$ therefore summarises sequence-region conservation, biochemical similarity,
druggability and local structural confidence. It is not experimental binding
evidence and does not prove that every member contains an equivalent 3D cavity.

#### 7. Structural score and treatment of three-dimensional evidence

The production structural base score was:

$$
S_{base}=0.55L+0.45C
$$

Ligandability supplies 55% and pocket-conservation evidence 45%. The slight
preference for $L$ reflects the importance of a consistently usable predicted
cavity, while $C$ records conservation of the associated region.

The workflow also supported a separately configured 3D refinement:

$$
S=(1-w_{3D})S_{base}+w_{3D}T
$$

for assessed groups, where:

$$
T=0.40TM_{min}+0.40o_{3D}
  +0.20\left(1-\min\left(\frac{d_{centroid}}{d_{max}},1\right)\right)
$$

$TM_{min}$ is the conservative minimum structural-alignment support,
$o_{3D}$ is the measured 3D pocket-overlap support, $d_{centroid}$ is the
distance between the compared pocket centroids and $d_{max}$ is the configured
distance at which the centroid contribution becomes zero. The centroid term is
bounded between zero and one: coincident centroids contribute one, the
contribution falls as the distance increases, and it reaches zero at or beyond
$d_{max}$.

In the recorded production profile:

$$
w_{3D}=0
$$

and therefore $S=S_{base}$. This is an important provenance point. The 3D
evidence was calculated and retained, but it was **not silently inserted into
the continuous structural score** after the production weighting was defined.
It remained visible through explicit fields recording assessment status,
same-position support, strict pocket-structure conservation, aligner agreement,
alternative-pocket sensitivity evidence and the applicable eligibility or
support gate.

Three-dimensional evidence could therefore affect interpretation, eligibility
and gate tier even though it contributed no numerical weight to $S$ in the
recorded profile. Alternative-pocket rescue also remained distinct from the
strict rank-one result: a lower-ranked pocket that aligned well was retained as
sensitivity evidence, but it did not rewrite the selected rank-one pocket or
retrospectively turn that pocket into a strict pass.

#### 8. Final integrated score

The final continuous score was:

$$
F=0.60P+0.40S
$$

Pre-structure evidence therefore contributes 60%, and ligandability plus
pocket-conservation evidence contributes 40%. Because the recorded profile has
$w_{3D}=0$, the formula can be expanded to:

$$
F=0.06D+0.21O+0.12A+0.21E+0.22L+0.18C
$$

| High-level evidence component | Effective contribution to $F$ |
|---|---:|
| Discovery | 6% |
| Orthology | 21% |
| Domain support | 12% |
| Expression | 21% |
| Ligandability | 22% |
| Pocket conservation | 18% |
| Direct 3D score contribution | 0% in the recorded production profile |

No single continuous component accounts for most of the score. The ranking
favours candidates supported across several evidence classes rather than those
with only one exceptional property. Nevertheless, $F$ is still a ranking score,
not a probability. For example, $F=0.80$ does not imply an 80% probability of E3
function or successful PROTAC development. Most importantly, $F$ does not
override hard gates; it orders candidates within the appropriate recorded
eligibility tier.

#### 9. Ordering, tie-breaks and evolutionary-group consolidation

The final table was not ordered by $F$ alone. It used a deterministic hierarchy:

1. **Recorded base-gate pass tier.** Candidates satisfying the required
   grant-aligned conditions are considered before candidates in a lower tier. A
   lower-tier candidate cannot move above a higher-tier candidate merely because
   its continuous score is larger.
2. **Final score.** Within the same gate tier, candidates are ordered by
   descending $F$.
3. **Evidence completeness.** If the gate tier and final score are tied, the
   candidate with greater recorded evidence completeness is placed first. This
   prevents extensive neutral missing-data substitutions from being treated as
   indistinguishable from a similarly scored but more completely assessed
   candidate.
4. **Stable cluster identifier.** If all preceding values are tied, the stable
   identifier supplies a reproducible final cluster-level tie-break. It carries
   no biological preference.

Multiple DeepClust sequence clusters can belong to the same primary OrthoFinder
group. Listing them independently would give some evolutionary groups several
opportunities to occupy the highest ranks. These rows were therefore
consolidated, and the best deterministically ranked DeepClust row became the
lead cluster representing that evolutionary group.

The consolidated groups were then ranked by the recorded final rank of the lead
cluster, followed where necessary by pre-structure group rank and the stable
evolutionary-group key. The stable key again provides reproducibility rather
than biological weighting.

#### How to interpret the resulting rank

A highly ranked evolutionary group is one that occupies the strongest
applicable gate tier, has strong integrated discovery, orthology, domain,
expression, ligandability and pocket-conservation evidence, has comparatively
complete supporting data, and remains highly placed after related DeepClust
clusters are consolidated.

A high rank does **not** establish that every member is an experimentally
confirmed E3 ligase; that every species contains an identical pocket; that the
predicted cavity will bind a sufficiently potent and selective ligand; that the
same ligand will bind every member; that ternary-complex formation will be
favourable; that target degradation will occur; or that a resulting PROTAC will
be effective in plants. Those questions require further structural, chemical
and experimental work.

The ranking should therefore be used as a transparent and reproducible way to
decide which evolutionary groups warrant the next stage of investigation. Its
strength is not that it turns heterogeneous computational evidence into a claim
of biological certainty. Its strength is that every component, gate,
missing-data decision, weight and tie-break is explicit and can be reproduced,
inspected and challenged.

The sliders below recompute scores only from values already present in the
completed resource. They create a sensitivity ranking and never modify the
authoritative ranks, gates, source files or pipeline outputs.
"""


def select_ranking_relation(*, relation_names: Sequence[str]) -> str | None:
    """Select the most authoritative relation usable for weight sensitivity."""
    preferred = (
        "final_evolutionary_candidate_prioritisation",
        "top_computational_review_shortlist",
        "top_50_computational_review_shortlist",
        "candidate_master_results",
        "final_candidate_prioritisation",
    )
    return next((name for name in preferred if name in relation_names), None)


def normalise_ranking_weights(
    *,
    weights: Mapping[str, Real],
    expected: Sequence[str],
) -> dict[str, float]:
    """Validate and normalise one non-negative weight group to sum to one."""
    if set(weights) != set(expected):
        raise ValueError("Ranking weights do not match the expected components.")
    converted: dict[str, float] = {}
    for name in expected:
        value = weights[name]
        if isinstance(value, bool) or not isinstance(value, Real):
            raise TypeError("Ranking weights must be real numbers.")
        numeric = float(value)
        if numeric < 0 or numeric > 1:
            raise ValueError("Ranking weights must be between 0 and 1.")
        converted[name] = numeric
    total = sum(converted.values())
    if total <= 0:
        raise ValueError("At least one ranking weight in each group must be positive.")
    return {name: value / total for name, value in converted.items()}


def _numeric_series(
    *, frame: pd.DataFrame, candidates: Sequence[str]
) -> pd.Series:
    """Return the first available bounded numeric component series."""
    column = next((name for name in candidates if name in frame.columns), None)
    if column is None:
        raise ValueError(
            "Ranking sensitivity requires one of: " + ", ".join(candidates)
        )
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0).clip(0.0, 1.0)


def _logical_series(*, frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a conservative Boolean interpretation of one stored field."""
    if column not in frame.columns:
        raise ValueError(f"Ranking sensitivity requires {column}.")
    values = frame[column]
    if pd.api.types.is_bool_dtype(values.dtype):
        return values.fillna(False).astype(bool)
    return values.astype("string").str.strip().str.lower().isin(
        {"true", "t", "1", "yes", "y", "pass"}
    )


def recompute_exploratory_ranking(
    *,
    frame: pd.DataFrame,
    prestructure_weights: Mapping[str, Real],
    ligandability_weights: Mapping[str, Real],
    structural_weights: Mapping[str, Real],
    final_weights: Mapping[str, Real],
    three_dimensional_weight: Real = 0.0,
    preserve_gate_tier: bool = True,
) -> pd.DataFrame:
    """Recompute a bounded, explicitly non-authoritative sensitivity ranking."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Ranking sensitivity requires a pandas DataFrame.")
    if frame.empty:
        return pd.DataFrame()
    if isinstance(three_dimensional_weight, bool) or not isinstance(
        three_dimensional_weight, Real
    ):
        raise TypeError("The 3D refinement weight must be a real number.")
    weight_3d = float(three_dimensional_weight)
    if weight_3d < 0 or weight_3d > 1:
        raise ValueError("The 3D refinement weight must be between 0 and 1.")

    pre = normalise_ranking_weights(
        weights=prestructure_weights,
        expected=tuple(DEFAULT_RANKING_WEIGHTS["prestructure"]),
    )
    ligand = normalise_ranking_weights(
        weights=ligandability_weights,
        expected=tuple(DEFAULT_RANKING_WEIGHTS["ligandability"]),
    )
    structural = normalise_ranking_weights(
        weights=structural_weights,
        expected=tuple(DEFAULT_RANKING_WEIGHTS["structural"]),
    )
    final = normalise_ranking_weights(
        weights=final_weights,
        expected=tuple(DEFAULT_RANKING_WEIGHTS["final"]),
    )

    discovery = _numeric_series(
        frame=frame, candidates=("lead_discovery_score", "discovery_score")
    )
    orthology = _numeric_series(
        frame=frame, candidates=("lead_orthology_score", "orthology_score")
    )
    domain = _numeric_series(
        frame=frame, candidates=("lead_domain_score", "domain_score")
    )
    expression = _numeric_series(
        frame=frame, candidates=("lead_expression_score", "expression_score")
    )
    exploratory_prestructure = (
        discovery * pre["discovery"]
        + orthology * pre["orthology"]
        + domain * pre["domain"]
        + expression * pre["expression"]
    )
    minimum_druggability = _numeric_series(
        frame=frame, candidates=("minimum_druggability_score",)
    )
    pocket_plddt = _numeric_series(
        frame=frame, candidates=("mean_pocket_plddt_fraction",)
    )
    member_mapping = _logical_series(
        frame=frame, column="all_assessed_members_pass_mapping"
    ).astype(float)
    predictor_agreement = _numeric_series(
        frame=frame, candidates=("predictor_agreement_fraction",)
    )
    exploratory_ligandability = (
        minimum_druggability * ligand["minimum_druggability"]
        + pocket_plddt * ligand["pocket_plddt"]
        + member_mapping * ligand["member_mapping"]
        + predictor_agreement * ligand["predictor_agreement"]
    )
    pocket_conservation = _numeric_series(
        frame=frame, candidates=("pocket_conservation_score",)
    )
    base_structural = (
        exploratory_ligandability * structural["ligandability"]
        + pocket_conservation * structural["pocket_conservation"]
    )
    three_dimensional = _numeric_series(
        frame=frame, candidates=("three_dimensional_pocket_score",)
    )
    if "three_dimensional_alignment_status" in frame.columns:
        alignment_status = frame["three_dimensional_alignment_status"].astype(
            "string"
        ).str.strip().str.upper()
        assessed = alignment_status.notna() & ~alignment_status.isin(
            {"", "NOT_ASSESSED", "NOT_STRUCTURALLY_ASSESSED"}
        )
    else:
        assessed = pd.Series(False, index=frame.index)
    exploratory_structural = base_structural.where(
        ~assessed,
        base_structural * (1.0 - weight_3d) + three_dimensional * weight_3d,
    )
    exploratory_final = (
        exploratory_prestructure * final["prestructure"]
        + exploratory_structural * final["structural"]
    )

    result = frame.copy()
    result["exploratory_prestructure_score"] = exploratory_prestructure
    result["exploratory_ligandability_score"] = exploratory_ligandability
    result["exploratory_structural_score"] = exploratory_structural
    result["exploratory_final_score"] = exploratory_final
    identity = next(
        (
            name
            for name in (
                "evolutionary_group_key",
                "primary_group_id",
                "lead_cluster_id",
                "cluster_id",
            )
            if name in result.columns
        ),
        None,
    )
    if identity is None:
        raise ValueError("Ranking sensitivity requires a stable group identifier.")
    completeness = (
        pd.to_numeric(result["evidence_completeness_fraction"], errors="coerce")
        .fillna(0.0)
        .clip(0.0, 1.0)
        if "evidence_completeness_fraction" in result.columns
        else pd.Series(0.0, index=result.index)
    )
    result["_e3_completeness"] = completeness
    sort_columns = ["exploratory_final_score", "_e3_completeness", identity]
    ascending = [False, False, True]
    if preserve_gate_tier and "grant_aligned_base_pass" in result.columns:
        result["_e3_gate_tier"] = _logical_series(
            frame=result, column="grant_aligned_base_pass"
        )
        sort_columns.insert(0, "_e3_gate_tier")
        ascending.insert(0, False)
    result = result.sort_values(
        sort_columns,
        ascending=ascending,
        kind="mergesort",
    ).reset_index(drop=True)
    result.insert(0, "exploratory_rank", range(1, len(result) + 1))
    recorded_rank_name = next(
        (
            name
            for name in ("final_evolutionary_rank", "final_rank", "computational_rank")
            if name in result.columns
        ),
        None,
    )
    if recorded_rank_name is not None:
        recorded_rank = pd.to_numeric(result[recorded_rank_name], errors="coerce")
        result.insert(
            1,
            "rank_change_positive_means_moved_up",
            (recorded_rank - result["exploratory_rank"]).astype("Int64"),
        )
    keep = [
        "exploratory_rank",
        "rank_change_positive_means_moved_up",
        recorded_rank_name,
        identity,
        "primary_group_type",
        "primary_group_id",
        "lead_cluster_id",
        "boss_review_status",
        "grant_aligned_prediction_status",
        "grant_aligned_base_pass",
        "grant_aligned_final_pass",
        "final_score",
        "exploratory_final_score",
        "prestructure_score",
        "exploratory_prestructure_score",
        "ligandability_score",
        "exploratory_ligandability_score",
        "structural_score",
        "exploratory_structural_score",
        "pocket_conservation_score",
        "three_dimensional_pocket_score",
        "evidence_completeness_fraction",
    ]
    keep = [name for name in keep if name is not None and name in result.columns]
    return result.loc[:, list(dict.fromkeys(keep))]
