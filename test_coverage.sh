#!/usr/bin/env bash
# Run the full test suite in parallel and report coverage.
#
# Usage:
#   ./test_coverage.sh              # auto-detect worker count
#   ./test_coverage.sh -n 4         # use 4 parallel workers
#   ./test_coverage.sh --unit       # unit tests only (fast, no Qt)
#   ./test_coverage.sh --integration # integration tests only
#   ./test_coverage.sh --no-cov     # skip coverage (fastest)
#
# Requires: poetry, QT_QPA_PLATFORM=offscreen for headless Qt

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
WORKERS="${XDIST_WORKERS:-auto}"
SCOPE="all"          # all | unit | integration
COVERAGE=true
FAIL_UNDER=50        # minimum coverage % to pass

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n)         WORKERS="$2"; shift 2 ;;
        -n*)        WORKERS="${1#-n}"; shift ;;
        --unit)     SCOPE="unit";        shift ;;
        --integration) SCOPE="integration"; shift ;;
        --no-cov)   COVERAGE=false;      shift ;;
        --fail-under) FAIL_UNDER="$2";   shift 2 ;;
        -h|--help)
            grep '^#' "$0" | head -20 | sed 's/^# \?//'
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Build pytest argument list
# ---------------------------------------------------------------------------
PYTEST_ARGS=()

# Test path
case "$SCOPE" in
    unit)        PYTEST_ARGS+=("tests/" "--ignore=tests/integration") ;;
    integration) PYTEST_ARGS+=("tests/integration/") ;;
    *)           PYTEST_ARGS+=("tests/") ;;
esac

# Parallel execution — xdist distributes by file so per-file fixtures stay
# on the same worker (avoids StateManager singleton races between files).
PYTEST_ARGS+=("-n" "$WORKERS" "--dist=loadfile")

# Coverage
if $COVERAGE; then
    PYTEST_ARGS+=(
        "--cov=src"
        "--cov-report=term-missing"
        "--cov-report=html"
        "--cov-report=xml"
        "--cov-fail-under=${FAIL_UNDER}"
    )
else
    PYTEST_ARGS+=("--no-cov")
fi

# Verbosity
PYTEST_ARGS+=("-v" "--no-header" "--tb=short")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
export QT_QPA_PLATFORM=offscreen

echo "=========================================="
echo " aerial-images-upload-gui test suite"
echo "=========================================="
echo " Scope   : $SCOPE"
echo " Workers : $WORKERS  (--dist=loadfile)"
if $COVERAGE; then
    echo " Coverage: enabled (fail-under=${FAIL_UNDER}%)"
else
    echo " Coverage: disabled"
fi
echo "------------------------------------------"
echo ""

START=$(date +%s)

poetry run pytest "${PYTEST_ARGS[@]}"

END=$(date +%s)
ELAPSED=$(( END - START ))

echo ""
echo "=========================================="
echo " Finished in ${ELAPSED}s"
if $COVERAGE; then
    echo " HTML report : htmlcov/index.html"
    echo " XML report  : coverage.xml"
fi
echo "=========================================="
