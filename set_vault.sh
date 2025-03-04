#!/bin/bash

export VAULT_ADDR="https://vault.ase.cit.tum.de"
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

VAULT_LOGIN_OUTPUT=$(vault login --method=oidc role=itg-admin)
VAULT_TOKEN=$(echo "$VAULT_LOGIN_OUTPUT" | grep 'hvs.' | head -n 1 | awk '{print $2}')

export VAULT_TOKEN
