#!/bin/bash
# Script to generate hash-pinned lockfiles for supply-chain security
# This ensures all dependencies are cryptographically verified during installation

set -e

echo "🔒 Generating hash-pinned lockfiles for supply-chain security..."

# Install pip-tools if not already installed
python -m pip install --quiet pip-tools==7.4.1

# Generate lockfile for application dependencies
echo "📦 Generating requirements-lock.txt..."
pip-compile --generate-hashes --allow-unsafe --output-file=requirements-lock.txt requirements.txt

# Create a temporary file for tooling dependencies
cat > /tmp/tools-requirements.txt <<EOF
ruff==0.8.4
bandit[toml]==1.8.0
pytest==8.3.4
EOF

# Generate lockfile for tooling dependencies
echo "🔧 Generating tools-requirements-lock.txt..."
pip-compile --generate-hashes --allow-unsafe --output-file=tools-requirements-lock.txt /tmp/tools-requirements.txt

# Clean up
rm /tmp/tools-requirements.txt

echo "✅ Lockfiles generated successfully!"
echo ""
echo "IMPORTANT: Review the generated lockfiles before committing:"
echo "  - requirements-lock.txt"
echo "  - tools-requirements-lock.txt"
echo ""
echo "These files pin exact versions with SHA256 hashes to prevent supply-chain attacks."
