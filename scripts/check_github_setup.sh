#!/usr/bin/env bash
# PE CoPilot — GitHub Repository Setup Checker
# Run from your local machine after creating the repo:
#   bash scripts/check_github_setup.sh
#
# Requires: gh CLI (authenticated), git

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
BOLD='\033[1m'

pass=0
fail=0
warn=0

check_pass()  { echo -e "  ${GREEN}✓${NC} $1"; pass=$((pass + 1)); }
check_fail()  { echo -e "  ${RED}✗${NC} $1"; fail=$((fail + 1)); }
check_warn()  { echo -e "  ${YELLOW}⚠${NC} $1"; warn=$((warn + 1)); }
section()     { echo -e "\n${BOLD}$1${NC}"; }

# ── Prerequisites ──────────────────────────────────────────────
section "Prerequisites"

if command -v gh &>/dev/null; then
    check_pass "gh CLI installed"
else
    check_fail "gh CLI not installed — install from https://cli.github.com"
    echo "       Cannot continue without gh. Exiting."
    exit 1
fi

if gh auth status &>/dev/null 2>&1; then
    check_pass "gh CLI authenticated"
else
    check_fail "gh CLI not authenticated — run: gh auth login"
    echo "       Cannot continue without auth. Exiting."
    exit 1
fi

if git rev-parse --is-inside-work-tree &>/dev/null 2>&1; then
    check_pass "Inside a git repository"
else
    check_fail "Not inside a git repository — run this from the pe-copilot folder"
    exit 1
fi

# ── Remote & Push Status ──────────────────────────────────────
section "Remote & Push"

REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
if [[ -n "$REMOTE_URL" ]]; then
    check_pass "Remote 'origin' configured: $REMOTE_URL"
else
    check_fail "No remote 'origin' — run: gh repo create pe-copilot --private --source=. --remote=origin --push"
fi

if [[ -n "$REMOTE_URL" ]]; then
    # Extract owner/repo from remote URL
    REPO=""
    if [[ "$REMOTE_URL" =~ github\.com[:/](.+/[^.]+)(\.git)?$ ]]; then
        REPO="${BASH_REMATCH[1]}"
    fi

    if [[ -n "$REPO" ]]; then
        # Check if remote has commits
        if git ls-remote --heads origin main &>/dev/null 2>&1; then
            check_pass "main branch pushed to remote"
        elif git ls-remote --heads origin master &>/dev/null 2>&1; then
            check_warn "Branch 'master' exists on remote — consider renaming to 'main': git branch -m master main && git push -u origin main"
        else
            check_fail "No branches pushed — run: git push -u origin main"
        fi
    fi
fi

# ── Repository Settings ──────────────────────────────────────
section "Repository Settings"

if [[ -n "${REPO:-}" ]]; then
    # Visibility
    VISIBILITY=$(gh repo view "$REPO" --json isPrivate --jq '.isPrivate' 2>/dev/null || echo "")
    if [[ "$VISIBILITY" == "true" ]]; then
        check_pass "Repository is private"
    elif [[ "$VISIBILITY" == "false" ]]; then
        check_warn "Repository is public — consider making it private until launch"
    else
        check_warn "Could not determine repository visibility"
    fi

    # Description
    DESCRIPTION=$(gh repo view "$REPO" --json description --jq '.description' 2>/dev/null || echo "")
    if [[ -n "$DESCRIPTION" && "$DESCRIPTION" != "null" ]]; then
        check_pass "Repository description set: $DESCRIPTION"
    else
        check_warn "No description — run: gh repo edit --description 'Financial data normalisation engine for PE fund managers'"
    fi

    # Default branch
    DEFAULT_BRANCH=$(gh repo view "$REPO" --json defaultBranchRef --jq '.defaultBranchRef.name' 2>/dev/null || echo "")
    if [[ "$DEFAULT_BRANCH" == "main" ]]; then
        check_pass "Default branch is 'main'"
    elif [[ -n "$DEFAULT_BRANCH" ]]; then
        check_warn "Default branch is '$DEFAULT_BRANCH' — consider 'main'"
    fi
else
    check_warn "Skipping repo settings checks (no remote detected)"
fi

# ── Branch Protection ─────────────────────────────────────────
section "Branch Protection (requires GitHub Pro for private repos)"

if [[ -n "${REPO:-}" ]]; then
    BP_RULES=$(gh api "repos/$REPO/branches/main/protection" 2>/dev/null || echo "NONE")
    if [[ "$BP_RULES" == "NONE" || "$BP_RULES" == *"Not Found"* || "$BP_RULES" == *"Branch not protected"* ]]; then
        check_warn "No branch protection on main — OK for free plan solo dev, add later if you upgrade"
    else
        check_pass "Branch protection enabled on main"
        # Check specific rules
        PR_REQUIRED=$(echo "$BP_RULES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('required_pull_request_reviews',{}).get('required_approving_review_count',0))" 2>/dev/null || echo "0")
        if [[ "$PR_REQUIRED" -gt 0 ]]; then
            check_pass "PR reviews required ($PR_REQUIRED approvals)"
        fi
    fi
fi

# ── Secrets (for CI/CD) ──────────────────────────────────────
section "Repository Secrets (needed for CI/CD deploy)"

REQUIRED_SECRETS=("GCP_PROJECT_ID" "WIF_PROVIDER" "WIF_SERVICE_ACCOUNT" "ANTHROPIC_API_KEY")

if [[ -n "${REPO:-}" ]]; then
    EXISTING_SECRETS=$(gh secret list --repo "$REPO" 2>/dev/null || echo "")
    for SECRET in "${REQUIRED_SECRETS[@]}"; do
        if echo "$EXISTING_SECRETS" | grep -q "$SECRET"; then
            check_pass "Secret '$SECRET' configured"
        else
            check_warn "Secret '$SECRET' not set — needed before first CI/CD deploy"
        fi
    done
else
    check_warn "Skipping secrets check (no remote detected)"
fi

# ── GitHub Actions ────────────────────────────────────────────
section "GitHub Actions"

if [[ -f ".github/workflows/deploy.yml" ]]; then
    check_pass "deploy.yml workflow file exists"
else
    check_fail "deploy.yml not found in .github/workflows/"
fi

if [[ -n "${REPO:-}" ]]; then
    ACTIONS_ENABLED=$(gh api "repos/$REPO/actions/permissions" --jq '.enabled' 2>/dev/null || echo "unknown")
    if [[ "$ACTIONS_ENABLED" == "true" ]]; then
        check_pass "GitHub Actions enabled"
    elif [[ "$ACTIONS_ENABLED" == "false" ]]; then
        check_fail "GitHub Actions disabled — enable in repo Settings → Actions → General"
    else
        check_warn "Could not verify Actions status"
    fi
fi

# ── Files Check ───────────────────────────────────────────────
section "Essential Files"

ESSENTIAL_FILES=(".gitignore" ".env.example" "Dockerfile" "pyproject.toml" ".dockerignore")
for F in "${ESSENTIAL_FILES[@]}"; do
    if [[ -f "$F" ]]; then
        check_pass "$F present"
    else
        check_fail "$F missing"
    fi
done

# Ensure .env is not tracked
if git ls-files --error-unmatch .env &>/dev/null 2>&1; then
    check_fail ".env is tracked by git — remove it: git rm --cached .env"
elif [[ -f ".env" ]]; then
    check_pass ".env exists locally but is NOT tracked (good)"
else
    check_pass ".env not present (will create from .env.example later)"
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}✓ $pass passed${NC}  ${RED}✗ $fail failed${NC}  ${YELLOW}⚠ $warn warnings${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

if [[ $fail -eq 0 ]]; then
    echo -e "\n${GREEN}${BOLD}GitHub setup looks good!${NC}"
    if [[ $warn -gt 0 ]]; then
        echo "  Warnings are non-blocking — address them when ready."
    fi
else
    echo -e "\n${RED}${BOLD}$fail issue(s) need fixing before proceeding.${NC}"
fi

echo ""
echo "Next steps after GitHub:"
echo "  1. Create GCP project + enable billing"
echo "  2. Enable APIs (Firestore, Cloud Run, Cloud Storage, Artifact Registry)"
echo "  3. Create .env from .env.example and fill in values"
echo "  4. Run: docker build -t pe-copilot . && docker run -p 8080:8080 --env-file .env pe-copilot"
echo ""
