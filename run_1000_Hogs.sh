

CONFIG_PATH="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/e3_end_to_end_runs/workflow_configs/grant_aligned_corrected_expressio
n_structural_all1972_v0_16_0_20260909.yaml"

REPOSITORY_ROOT="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/E3_project_draft"

cd "${REPOSITORY_ROOT}/e3_end_to_end_workflow"


CONFIG_PATH="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/analysis/e3_end_to_end_runs/workflow_configs/grant_aligned_corrected_expressio
n_structural_all1972_v0_16_0_20260909.yaml"

REPOSITORY_ROOT="/gpfs/uod-scale-01/cluster/gjb_lab/pthorpe001/2026_E3_protac/E3_project_draft"

cd "${REPOSITORY_ROOT}/e3_end_to_end_workflow"

conda run \
    --no-capture-output \
    --name e3_end_to_end_workflow \
    bash ./run_e3_end_to_end.sh \
    --config "${CONFIG_PATH}" \
    --profile slurm \
    --unlock \
    -- \
    --slurm-status-command sacct




bash ./submit_e3_controller_slurm.sh \
    --config "${CONFIG_PATH}" \
    --controller-account barton \
    --controller-partition barton \
    --controller-qos 4week \
    --controller-runtime 28-00:00:00 \
    --conda-environment e3_end_to_end_workflow \
    --account barton \
    --partition barton \
    --max-jobs 50 \
    --resume \
    -- \
    --slurm-status-command sacct
