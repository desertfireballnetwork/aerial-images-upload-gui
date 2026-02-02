#!/bin/bash
# Test coverage script for uploader

set -e

echo "Running tests with coverage..."

poetry run pytest \
    --cov=src \
    --cov-report=html \
    --cov-report=xml \
    --cov-report=term \
    --cov-fail-under=70 \
    -v

echo ""
echo "Coverage report generated:"
echo "  HTML: htmlcov/index.html"
echo "  XML: coverage.xml"
