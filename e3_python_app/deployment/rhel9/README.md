# RHEL 9 deployment for the E3 milestone application

This directory deploys `e3_python_app`, the milestone application in
`E3_project_draft`, as a persistent and read-only service. It does not deploy the
separate experimental OrthoFinder interrogation application.

The installer targets the University of Dundee RHEL 9 VM
`e3tgts-ls-at1.dundee.ac.uk`. It keeps SELinux enforcing, creates an unprivileged
`e3app` service account, installs Python 3.11 in an isolated virtual environment,
validates the DuckDB and optional structural-review bundles, and enables automatic
restart after the scheduled Tuesday reboot.

## Application and release layout

Application code is installed under `/opt/e3-python-app`. Immutable, fingerprinted
releases are placed under `/srv/e3-python-app/releases`; the `current` symbolic link
selects the active release. Application logs use the system journal. Only runtime
cache, state and log directories are writable by the service account.

The integrated DuckDB is required. The two pocket-review directories are strongly
recommended because they provide the plant-only and combined human-and-plant 3D
views. The installer also accepts the optional separate expression DuckDB and a
reviewed custom taxonomy mapping.

## Prepare the VM

```bash
sudo dnf install --assumeyes git
git clone https://github.com/peterthorpe5/E3_project_draft.git
cd E3_project_draft
sudo ./e3_python_app/deployment/rhel9/install_e3_python_app.sh \
  --prepare-only \
  --repository-ref main
```

This first phase installs the application and service assets but does not start the
service because no scientific release has been supplied.

## Transfer the release

Transfer the required database and any companion directories to a staging directory
in the administrator's home. For the established portable-release layout, this can
be the complete release directory:

```bash
rsync --archive --info=progress2 \
  /path/to/portable_visualisation_release/ \
  pthorpe001@e3tgts-ls-at1.dundee.ac.uk:~/portable_visualisation_release/
```

The expected sources within that release are:

```text
portable_visualisation_release/
├── e3_integrated_resource.duckdb
└── human_plant_structural_extension/
    ├── plant_pocket_review/
    └── pocket_review/
```

The source directory remains untouched. The installer creates and validates its own
managed copy.

## Install and start the complete application

```bash
cd ~/E3_project_draft
PORTABLE_ROOT="$HOME/portable_visualisation_release"

sudo ./e3_python_app/deployment/rhel9/install_e3_python_app.sh \
  --resource-duckdb \
    "${PORTABLE_ROOT}/e3_integrated_resource.duckdb" \
  --pocket-review-dir \
    "${PORTABLE_ROOT}/human_plant_structural_extension/plant_pocket_review" \
  --human-plant-review-dir \
    "${PORTABLE_ROOT}/human_plant_structural_extension/pocket_review" \
  --repository-ref main \
  --max-rows 1000
```

If only the integrated DuckDB is currently available, a core deployment is valid:

```bash
sudo ./e3_python_app/deployment/rhel9/install_e3_python_app.sh \
  --resource-duckdb "$HOME/e3_integrated_resource.duckdb" \
  --repository-ref main \
  --max-rows 1000
```

The relational pages, searches and TSV/Excel/PDF outputs remain available. The 3D
plant and human-and-plant pages will explicitly report that their review bundles are
not configured. Rerun the complete command later with `--replace-release` to activate
the complete release.

## Test privately through SSH

The safe default listens on `127.0.0.1:8501`. On the workstation, open an SSH
tunnel:

```bash
ssh -L 8501:127.0.0.1:8501 pthorpe001@e3tgts-ls-at1.dundee.ac.uk
```

Then visit <http://127.0.0.1:8501>. On the VM:

```bash
sudo systemctl status e3-python-app.service
sudo journalctl --unit e3-python-app.service --follow
curl --fail --silent http://127.0.0.1:8501/_stcore/health
```

## Permit the University reverse proxy

Keep the loopback-only configuration until IT supplies the exact source IP or CIDR
of `www-2`. Rerun the same complete release command with these additional options:

```bash
  --server-address 0.0.0.0 \
  --server-port 8501 \
  --firewall-source WWW_2_PROXY_IP_OR_CIDR
```

The installer replaces only the firewall rule it previously created for this app.
It never opens port 8501 generally. IT's Vhost should terminate HTTPS, preserve
WebSocket upgrade headers and proxy to `134.36.6.128:8501`.

## Repeatability and updates

Every installed release has a content-derived identifier and `SHA256SUMS.txt`.
Rerunning the command with identical sources reuses and revalidates that release. A
different release must be activated explicitly with `--replace-release`; earlier
releases are retained for review and rollback. The exact Git commit and installed
Python packages are recorded under `/opt/e3-python-app`.

After the scheduled Tuesday maintenance reboot, verify:

```bash
systemctl is-enabled e3-python-app.service
systemctl is-active e3-python-app.service
curl --fail --silent http://127.0.0.1:8501/_stcore/health
```
