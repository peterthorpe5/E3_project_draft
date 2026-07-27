"""Static contracts for the University of Dundee Slurm driver scripts."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


class SlurmScriptContractTests(unittest.TestCase):
    """Prevent regression of required Slurm and full-run safeguards."""

    def read_script(self, name: str) -> str:
        """Return one repository shell script as text.

        Args:
            name: Shell script filename below ``scripts``.

        Returns:
            UTF-8 script text.
        """

        return (SCRIPTS / name).read_text(encoding="utf-8")

    def test_worker_uses_dundee_allocation(self):
        """Require the agreed Barton account and general partition."""

        text = self.read_script("slurm_full_onekp_job.sh")
        self.assertIn("#SBATCH --account=barton", text)
        self.assertIn("#SBATCH --partition=general", text)
        self.assertNotIn("qsub", text)
        self.assertNotIn("#$", text)

    def test_submission_uses_sbatch_and_conservative_resources(self):
        """Require Slurm submission with explicit CPU, memory and time values."""

        text = self.read_script("submit_full_onekp_slurm.sh")
        self.assertIn("sbatch", text)
        self.assertIn('ACCOUNT="barton"', text)
        self.assertIn('PARTITION="general"', text)
        self.assertIn('SLURM_MEMORY="256G"', text)
        self.assertIn('DIAMOND_MEMORY="220G"', text)
        self.assertIn('WALLTIME="7-00:00:00"', text)
        self.assertIn('MIN_RESULTS_FREE_GIB=150', text)
        self.assertIn('MIN_SCRATCH_FREE_GIB=100', text)
        self.assertIn("validate-full-cluster-inputs", text)
        self.assertIn("source_input_preflight.json", text)
        self.assertIn("24.7.1", text)

    def test_worker_generates_onekp_metadata_configuration(self):
        """Require generated config, 1KP parser use and job-local scratch."""

        text = self.read_script("slurm_full_onekp_job.sh")
        self.assertIn("create-full-cluster-config", text)
        self.assertIn("SLURM_TMPDIR", text)
        self.assertIn("full_onekp_plus.cluster.config.yaml", text)
        self.assertIn("validate_completed_result", text)
        self.assertIn("create_review_bundle", text)
        self.assertIn("check_free_space_gib", text)
        self.assertIn("E3_MIN_RESULTS_FREE_GIB", text)
        self.assertIn("E3_MIN_SCRATCH_FREE_GIB", text)
        self.assertIn("snakemake_dry_run.log", text)
        self.assertIn("complete dry-run log follows", text)

    def test_scripts_use_defensive_shell_mode(self):
        """Require strict shell error handling in all new Slurm scripts."""

        for name in (
            "submit_full_onekp_slurm.sh",
            "slurm_full_onekp_job.sh",
            "check_full_onekp_slurm.sh",
        ):
            with self.subTest(script=name):
                text = self.read_script(name)
                self.assertIn("set -Eeuo pipefail", text)

    def test_worker_retains_scratch_after_failure(self):
        """Require scratch cleanup only after a successful worker exit."""

        text = self.read_script("slurm_full_onekp_job.sh")
        self.assertIn('"${exit_code}" -eq 0', text)
        self.assertIn(
            'Scratch has been retained for diagnosis: ${JOB_SCRATCH}',
            text,
        )

    def test_status_script_reports_queue_accounting_and_bundle(self):
        """Require usable monitoring and completed-bundle discovery."""

        text = self.read_script("check_full_onekp_slurm.sh")
        self.assertIn("squeue", text)
        self.assertIn("sacct", text)
        self.assertIn("workflow_complete.ok", text)
        self.assertIn("review_bundle_path.txt", text)


if __name__ == "__main__":
    unittest.main()
