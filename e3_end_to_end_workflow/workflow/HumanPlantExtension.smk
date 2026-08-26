"""Standalone entry point for adding human structures to a completed plant run."""

from pathlib import Path


HUMAN_PLANT_CONFIG_PATH = Path(workflow.configfiles[0]).expanduser().resolve()
HUMAN_PLANT_CONFIG_BASE = HUMAN_PLANT_CONFIG_PATH.parent
HUMAN_PLANT_DEFAULT_PARENT_CONFIG = HUMAN_PLANT_CONFIG_PATH
HUMAN_PLANT_EXTENSION = dict(config.get("human_plant_extension", {}))
if not HUMAN_PLANT_EXTENSION.get("enabled", False):
    raise ValueError("human_plant_extension.enabled must be true")

include: "human_plant_extension_rules.smk"


rule all:
    input:
        str(HUMAN_PLANT_PLANT_REVIEW_MANIFEST),
        str(HUMAN_PLANT_REVIEW_MANIFEST)
