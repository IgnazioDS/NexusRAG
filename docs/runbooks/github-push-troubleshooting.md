# GitHub Push Troubleshooting

Use this runbook when `git push`/`git pull` fails due to TLS, DNS, or transport issues.

## 1. Quick diagnostics

Run the non-destructive helper:

```bash
./scripts/git_network_diag.sh
```

Or run checks manually:

```bash
git remote -v
git ls-remote origin HEAD
curl -Iv https://github.com
```

Inspect SSL-related environment overrides:

```bash
echo "${GIT_SSL_NO_VERIFY:-<unset>}"
echo "${GIT_SSL_CAINFO:-<unset>}"
echo "${CURL_CA_BUNDLE:-<unset>}"
echo "${SSL_CERT_FILE:-<unset>}"
```

Do not disable TLS verification in this repository or shell profile.

## 2. Validate remote URL and credentials

HTTPS remote:

```bash
git remote set-url origin https://github.com/IgnazioDS/NexusRAG.git
git ls-remote origin HEAD
```

SSH fallback (if SSH key is configured in GitHub):

```bash
ssh -T git@github.com
git remote set-url origin git@github.com:IgnazioDS/NexusRAG.git
git ls-remote origin HEAD
```

## 3. Push fallback via GitHub CLI (optional)

If `gh` is installed and authenticated:

```bash
gh auth status
git push origin HEAD
```

## 4. Common resolution checklist

- Confirm system clock is accurate (TLS cert validation depends on it).
- Confirm corporate proxy is not intercepting TLS.
- Confirm local CA trust store is healthy (`curl -Iv https://github.com`).
- Confirm VPN/private DNS is not overriding `github.com`.
