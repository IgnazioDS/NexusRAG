#!/usr/bin/env bash
set -euo pipefail

# Run non-destructive GitHub connectivity checks to diagnose push/pull TLS and routing issues.
echo "== git remote -v =="
git remote -v
echo

echo "== git ls-remote origin HEAD =="
git ls-remote origin HEAD
echo

echo "== curl -Iv https://github.com =="
curl -Iv https://github.com
echo

# Print SSL-related Git env toggles so operators can spot accidental overrides without changing them.
echo "== SSL-related environment variables =="
echo "GIT_SSL_NO_VERIFY=${GIT_SSL_NO_VERIFY:-<unset>}"
echo "GIT_SSL_CAINFO=${GIT_SSL_CAINFO:-<unset>}"
echo "GIT_CURL_VERBOSE=${GIT_CURL_VERBOSE:-<unset>}"
echo "CURL_CA_BUNDLE=${CURL_CA_BUNDLE:-<unset>}"
echo "SSL_CERT_FILE=${SSL_CERT_FILE:-<unset>}"
