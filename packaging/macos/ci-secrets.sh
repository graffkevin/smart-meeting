#!/usr/bin/env bash
# Stores once, from the Mac holding the certificate, the GitHub secrets the Release workflow
# (.github/workflows/release.yml) signs and notarizes the Mac app with. The values go straight from
# this terminal to GitHub (gh secret set), never into a file or the command line.
#
#   1. Keychain Access > login > My Certificates > "Developer ID Application: …" > right click,
#      Export… as DeveloperID.p12, with a password
#   2. appleid.apple.com > Sign-In and Security > App-Specific Passwords: a new one ("GitHub CI")
#   3. packaging/macos/ci-secrets.sh DeveloperID.p12
set -euo pipefail

p12="${1:?usage: packaging/macos/ci-secrets.sh DeveloperID.p12}"
[ -f "$p12" ] || { echo "Fichier introuvable : $p12"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh n'est pas connecté : gh auth login"; exit 1; }

# Team ID of the Developer ID certificate of this Mac, e.g. "Developer ID Application: Name (TEAMID)"
team="$(security find-identity -v -p codesigning \
  | sed -nE 's/.*"Developer ID Application: .*\(([A-Z0-9]{10})\)".*/\1/p' | head -1)"
read -rp "Team ID [${team:-?}] : " answer
team="${answer:-$team}"
[ -n "$team" ] || { echo "Team ID manquant"; exit 1; }
read -rp "Apple ID (e-mail du compte développeur) : " apple_id
read -rsp "Mot de passe du .p12 : " p12_password; echo
read -rsp "Mot de passe pour app (xxxx-xxxx-xxxx-xxxx) : " app_password; echo

# The .p12 must open with its password and hold a private key
tmp="$(mktemp -d)"
trap 'security delete-keychain "$tmp/check.keychain-db" 2>/dev/null || true; rm -rf "$tmp"' EXIT
security create-keychain -p check "$tmp/check.keychain-db"
security import "$p12" -k "$tmp/check.keychain-db" -P "$p12_password" >/dev/null \
  || { echo "Le .p12 ne s'ouvre pas avec ce mot de passe"; exit 1; }
security find-identity -v -p codesigning "$tmp/check.keychain-db" | grep -q "Developer ID Application" \
  || { echo "Pas de certificat « Developer ID Application » avec sa clé dans ce .p12"; exit 1; }

base64 -i "$p12" | gh secret set MACOS_CERTIFICATE
printf '%s' "$p12_password" | gh secret set MACOS_CERTIFICATE_PASSWORD
printf '%s' "$apple_id" | gh secret set APPLE_ID
printf '%s' "$app_password" | gh secret set APPLE_APP_PASSWORD
printf '%s' "$team" | gh secret set APPLE_TEAM_ID
echo "Secrets enregistrés. Le .p12 peut être supprimé : rm '$p12'"
