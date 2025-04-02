#!/bin/bash

set -x VAULT_ADDR "https://vault.ase.cit.tum.de"
set -x OBJC_DISABLE_INITIALIZE_FORK_SAFETY "YES"

set VAULT_LOGIN_OUTPUT (vault login --method=oidc role=itg-artemis-admin | string escape)
# Regex for vault token based on https://discuss.hashicorp.com/t/what-is-regex-pattern-for-hashicorp-vault-tokens/50502/2
set -x VAULT_TOKEN (echo "$VAULT_LOGIN_OUTPUT" | grep -oE 'hv[sb]\.(?:[A-Za-z0-9]{24}|[A-Za-z0-9_-]{91,})' | head -n 1)
