# Artemis-Ansible

This repository contains the Ansible configuration for the [Artemis Ansible Collection](https://github.com/ls1intum/artemis-ansible-collection), which is responsible for setting up the TUM Artemis production, staging, and test environments.

If you want a configuration change to be applied to one of our environments, please check first if there is already a configuration option available in the ansible collection.
If not, you have to adapt the collection first and open a PR there.

When there is a configuration option available, you can change the configuration in the `host_vars` or `group_vars` files of this repository and open a PR.
We will then review the PR and apply the changes to the respective environment.

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
   After review, we will apply new configuration to the respective environment.

---

## Usage

> **Note:**  
> This section is relevant only for members of the admin team who deploy changes to the Artemis environments.

> **Prerequisites:**  
> Ensure you have followed the installation instructions and properly configured your SSH access.

### Activating the Virtual Environment

```bash
source venv/bin/activate # Adjust command if using fish (.fish) or csh (.csh)
```

Once activated, you can run Ansible commands.

### Secrets Management

We manage secrets using Hashicorps Vault.
The base configuration is already set up in this repository's Ansible configuration
Make sure you have the vault cli installed.

#### Prerequisites

- Vault CLI must be installed
- You must be connected to the il01 VPN and have admin permissions to access vault.

#### Automated Login

```sh
source set_vault.sh # Use set_vault.fish for fish shell
```

To access Artemis Production, modify `set_vault.sh` by replacing `itg-admin` with `itg-artemis-admin`.

#### Manual Login

```sh
export VAULT_ADDR="https://vault.ase.cit.tum.de"
vault login --method=oidc role=itg-admin
```

After login, a token will be printed in the command output.
Export it for Ansible:

```sh
export VAULT_TOKEN=hvs.<token>
```

## Installation

It is recommended to install Ansible and ansible-lint inside a virtual environment: 

```sh
python3 -m venv venv
source venv/bin/activate # Adjust command if using fish (.fish) or csh (.csh)
pip3 install -r requirements.txt

ansible-galaxy collection install -r requirements.yml --force
ansible-galaxy install -r requirements.yml --force
ansible-galaxy install -r ~/.ansible/collections/ansible_collections/ls1intum/artemis/requirements.yml
```

### SSH Configuration 

To ensure proper SSH access, append the following lines to the very bottom of your `~/.ssh/config` file

```less
Host *
    Hostname %h
    User <TUMID>
```

## Common Tasks

### Running `ansible-lint`

```sh
ansible-lint --offline -c .ansible-lint
```

### Updating Artemis Configuration on a Host

Modify the necessary variables in `host_var` or `group_var`, then apply the changes.

For **native servers**:

```bash
ansible-playbook playbooks/<server>/node-update-config.yml
```

For **Docker-based servers**:

```bash
ansible-playbook playbooks/artemis-tests/artemis-tests.yml
```

> **Warning:** This will restart and redeploy the Docker containers.

### Connecting to Services

### Registry Access

The registry is accessible within the il01 VPN.
Use the domain of the registry host to open it in a browser.
Credentials are stored in Vault.

### Database Access

Databases are accessible only from the database hosts or the WireGuard network.
To connect, set up an SSH tunnel.

The passwords for the user are stored in Vault.
The username is configured in the `group_vars` files.

We recommend using a tool like DataGrip to connect to the database.
Otherwise, you can manually create an SSH tunnel.

#### Creating an SSH Tunnel

```bash
ssh -L 36306:127.0.0.1:3306 artemis-production-db.artemis.in.tum.de
```

Once the tunnel is active, the database is accessible on port `36306` on your local machine

### Notes on test servers

The test server host configs are split up into different files (e.g. integrated code lifecycle, LocalVC/Jenkins, and common config).
These configurations are managed using Ansible host groups.
Each test server is assigned multiple host groups based on its setup.
The mappings are defined in the hosts file.
