#!/bin/bash
# DVC Setup Script for Ketchup Backend

echo "Setting up DVC for Ketchup Backend..."

# Check if DVC is installed
if ! command -v dvc &> /dev/null; then
    echo "❌ DVC not found. Installing via pip..."
    pip install dvc dvc-gs
fi

# Initialize DVC if not already initialized
if [ ! -d ".dvc" ]; then
    echo "Initializing DVC repository..."
    dvc init
    echo "DVC initialized"
else
    echo "DVC already initialized"
fi

# Create data directories if they don't exist
echo "Creating data directories..."
mkdir -p data/raw
mkdir -p data/processed
mkdir -p data/metrics
mkdir -p data/reports
mkdir -p data/statistics
mkdir -p data/analysis/plots

# Create placeholder files to ensure directories are tracked
touch data/raw/.gitkeep
touch data/processed/.gitkeep
touch data/metrics/.gitkeep
touch data/reports/.gitkeep
touch data/statistics/.gitkeep
touch data/analysis/plots/.gitkeep

# Add data directories to .gitignore (DVC will track them)
echo "Updating .gitignore for DVC tracking..."
cat >> .gitignore << EOF

# DVC tracked data directories
/data/raw/*.csv
/data/processed/*.csv
/data/statistics/*.json
EOF

echo "DVC setup complete!"
echo ""
echo "Next steps:"
echo "  1. Configure remote storage: dvc remote add -d myremote gs://your-bucket/path"
echo "  2. Run pipeline: dvc repro"
echo "  3. Push data: dvc push"
echo ""
echo "View pipeline: dvc dag"
