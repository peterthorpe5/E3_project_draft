"""Tests for the reproducible RHEL 9 deployment assets."""

from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_ROOT = PROJECT_ROOT / "deployment" / "rhel9"
INSTALLER = DEPLOYMENT_ROOT / "install_e3_python_app.sh"
STARTER = DEPLOYMENT_ROOT / "start_e3_service.sh"
SERVICE = DEPLOYMENT_ROOT / "e3-python-app.service"


def test_deployment_scripts_have_valid_bash_syntax_and_named_help() -> None:
    """Both scripts parse as Bash and the installer documents named controls."""

    subprocess.run(["bash", "-n", str(INSTALLER), str(STARTER)], check=True)
    completed = subprocess.run(
        ["bash", str(INSTALLER), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "--resource-duckdb PATH" in completed.stdout
    assert "--pocket-review-dir PATH" in completed.stdout
    assert "--human-plant-review-dir PATH" in completed.stdout
    assert "--prepare-only" in completed.stdout
    assert "--repository-url URL" in completed.stdout
    assert "--firewall-source CIDR" in completed.stdout


def test_installer_fails_closed_at_host_and_firewall_boundaries() -> None:
    """External binding requires one narrow proxy source and never disables SELinux."""

    source = INSTALLER.read_text(encoding="utf-8")
    assert "set -Eeuo pipefail" in source
    assert "A non-loopback --server-address requires --firewall-source" in source
    assert "--add-rich-rule" in source
    assert "--add-port" not in source
    assert "setenforce" not in source.casefold()
    assert "--replace-release" in source
    assert "SHA256SUMS.txt" in source
    assert "systemctl enable" in source

    rejected = subprocess.run(
        [
            "bash",
            "-c",
            f"source {INSTALLER!s}; parse_arguments --prepare-only "
            "--server-address 0.0.0.0",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 2
    assert "requires --firewall-source" in rejected.stderr


def test_installer_argument_functions_accept_safe_preparation() -> None:
    """Named parsing accepts bounded values and a private preparation run."""

    accepted = subprocess.run(
        [
            "bash",
            "-c",
            f"source {INSTALLER!s}; parse_arguments --prepare-only "
            "--server-address 127.0.0.1 --server-port 8501 --max-rows 1000",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert accepted.returncode == 0, accepted.stderr


def test_repository_ref_resolution_emits_only_the_checkout_ref() -> None:
    """Git validation output must not contaminate the resolved ref value."""

    completed = subprocess.run(
        [
            "bash",
            "-c",
            f"source {INSTALLER!s}; "
            "git() { printf 'mock-commit-sha\\n'; return 0; }; "
            "resolve_repository_ref main",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout == "origin/main\n"


def test_service_starter_uses_only_named_application_options() -> None:
    """The service wrapper preserves every supported release companion path."""

    source = STARTER.read_text(encoding="utf-8")
    assert "--resource-duckdb" in source
    assert "--expression-duckdb" in source
    assert "--pocket-review-dir" in source
    assert "--human-plant-review-dir" in source
    assert "--taxonomy-map" in source
    assert 'exec "${command[@]}"' in source


def test_systemd_unit_is_restartable_read_only_and_bounded() -> None:
    """The long-running service has restart, write-path and resource controls."""

    source = SERVICE.read_text(encoding="utf-8")
    assert "User=e3app" in source
    assert "Restart=on-failure" in source
    assert "ProtectSystem=strict" in source
    assert "NoNewPrivileges=true" in source
    assert "MemoryMax=12G" in source
    assert "ReadWritePaths=" in source
    assert "EnvironmentFile=/etc/e3-python-app.env" in source
    assert "STREAMLIT_BROWSER_GATHER_USAGE_STATS=false" in source
