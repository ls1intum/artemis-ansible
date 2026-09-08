# Artemis-Ansible

This repository contains the Ansible configuration for the [Artemis Ansible Collection](https://github.com/ls1intum/artemis-ansible-collection), which is responsible for setting up the TUM Artemis production, staging, and test environments.

## Requesting Configuration Changes

If you need a configuration change for one of the environments, follow these steps:

1. **Check for an existing configuration option**  
   First, verify whether the required configuration option already exists in the Ansible collection.

2. **Modify the Ansible collection if needed**  
   If no existing configuration option is available, update the Ansible collection first and submit a pull request to that repository.

3. **Apply the configuration change**  
   Once the configuration option is available, update the relevant `host_vars` or `group_vars` files in this repository and open a pull request.  
   After review, we will apply the new configuration to the respective environment.

---

## Installation & Update

> **Note:**
> This section is relevant only for members of the admin team who deploy changes to the Artemis environments.

It is recommended to install Ansible and ansible-lint inside a virtual environment:

```sh
python3 -m venv venv
source venv/bin/activate # Adjust command if using fish (.fish) or csh (.csh)
pip3 install -r requirements.txt

ansible-galaxy collection install -r requirements.yml --force
ansible-galaxy install -r requirements.yml --force
ansible-galaxy install -r ~/.ansible/collections/ansible_collections/ls1intum/artemis/requirements.yml
```

To update the Ansible collection, run the last four commands again.

### SSH Configuration

To ensure proper SSH access, append the following lines to the very bottom of your `~/.ssh/config` file

```text
Host *
    Hostname %h
    User <TUMID>
```

## Usage

> **Note:**  
> This section is relevant only for members of the admin team who deploy changes to the Artemis environments.

### Activating the Virtual Environment

```sh
source venv/bin/activate # Adjust command if using fish (.fish) or csh (.csh)
```

Once activated, you can run Ansible commands.

### Secrets Management

We manage secrets using Hashicorp Vault.
The base configuration is already set up in this repository's Ansible configuration.

Hashicorp provides comprehensive [documentation and tutorials](https://developer.hashicorp.com/vault/tutorials) on how to use Vault.

#### Prerequisites

- Vault CLI must be [installed](https://developer.hashicorp.com/vault/install)
- You must be connected to the AET VPN and have admin permissions to access [vault](https://vault.aet.cit.tum.de/).

#### Automated Login

```sh
source set_vault.sh # Use set_vault.fish for fish shell
```

#### Manual Login

```sh
export VAULT_ADDR="https://vault.aet.cit.tum.de"
vault login --method=oidc role=itg-artemis-admin
```

After login, a token will be printed in the command output.
Export it for Ansible:

```sh
export VAULT_TOKEN=hvs.<token>
```

## Common Tasks

### Running `ansible-lint`

```sh
ansible-lint
```

### Deploying New Artemis Version

```sh
ansible-playbook playbooks/<server>/nodes-version-update.yml -e artemis_version=<version> # For test & staging servers
ansible-playbook playbooks/artemis-production/production-nodes-version-update.yml -e artemis_version=<version> # For production
```

The `<version>` variable can be set to a specific [GitHub release tag](https://github.com/ls1intum/Artemis/releases) — either 3-segment (`9.1.2`) or 2-segment (`9.2`) — or to an absolute path to a local Artemis executable (e.g., `/home/user/Artemis.war`).

> **YAML quoting (important for 2-segment tags):** when recording a 2-segment version inside a `group_vars` or `host_vars` file, always quote it: `artemis_version: "9.2"`. Without quotes YAML parses `9.2` as a float and `9.10` silently becomes `9.1`. Passing `-e artemis_version=9.2` on the command line (`key=value` form) is string-safe, but inline JSON/YAML-form extra-vars (`-e '{"artemis_version": 9.2}'`) still need explicit quoting.

### Upgrading PostgreSQL to a New Major Version

The `geerlingguy.postgresql` role installs packages and manages configuration but never
moves data between major versions. The pinned version lives in
`group_vars/artemis_prod_like_postgres.yml` (`postgresql_version` and the matching
`postgresql_*` path variables); the PGDG apt repository that provides it is added by each
environment's `db.yml`.

To move an existing database host to the pinned version, stop Artemis first, then run the
reusable migration playbook (Debian `pg_upgradecluster` under the hood; it takes a full
`pg_dumpall` backup into `/var/lib/postgresql/upgrade-backups` before touching anything):

```sh
ansible-playbook playbooks/artemis-staging1/nodes-stop-artemis.yml
ansible-playbook playbooks/artemis-staging1/db.yml                                   # install the new server packages
ansible-playbook playbooks/postgres-major-upgrade.yml -e postgres_upgrade_target=artemis_staging1_db
ansible-playbook playbooks/artemis-staging1/db.yml                                   # reapply the tuned postgresql.conf on the new cluster
ansible-playbook playbooks/artemis-staging1/nodes-start-artemis.yml
```

The playbook auto-detects the source version and skips a host that is already on the
target. Useful extra vars: `-e pg_target_version=<major>` (override the pin),
`-e pg_upgrade_method=pg_upgrade_link` (hard-link instead of copy, for a large database),
`-e pg_drop_old_cluster=true` (remove the old cluster instead of leaving it stopped),
`-e pg_upgrade_confirmed=true` (skip the interactive prompt).

### Updating Artemis Configuration on a Host

Modify the necessary variables in `host_var` or `group_var`, then apply the changes.

The test server host configs are split up into different files (e.g., integrated code lifecycle, LocalVC/Jenkins, and common config).
These configurations are managed using Ansible host groups.
Each test server is assigned multiple host groups based on its setup.
The mappings are defined in the hosts file.

The `artemis_prod_like_*.yml` files contain shared configurations for all production-like servers (production and staging servers).
The `artemis_production*.yml`, `artemis_staging1*.yml`, and `artemis_staging_localci*.yml` files contain configurations specific to the respective instance.

For **native servers**:

```sh
ansible-playbook playbooks/<server>/nodes-update-config.yml --diff --check # For native staging servers
ansible-playbook playbooks/artemis-production/production-nodes-update-config.yml --diff --check # For production servers
```

After review, run the same command without `--check` to apply the changes.

For **Docker-based test servers**:

```sh
ansible-playbook playbooks/artemis-tests/artemis-tests.yml --diff --check
```

After review, run the same command without `--check` to apply the changes.

> **Warning:** This will restart and redeploy the Docker containers.

### Connecting to Services

#### Registry Access

The registry is accessible within the AET VPN.
Use the domain of the registry host to open it in a browser.
Credentials are stored in Vault.

#### Database Access

Databases are accessible only from the database hosts or the WireGuard network.
To connect, set up an SSH tunnel.

The passwords for the user are stored in Vault.
The username is configured in the `group_vars` files.

We recommend using a tool like DataGrip to connect to the database.
Otherwise, you can manually create an SSH tunnel.

##### Creating an SSH Tunnel

```sh
ssh -L 36306:127.0.0.1:3306
```

Once the tunnel is active, the database is accessible on port `36306` on your local machine
