#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# setup.sh — One-shot setup for PaperDigest
# Run: bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

ENV_NAME="paperdigest"

echo ""
echo "  ██████╗  █████╗ ██████╗ ███████╗██████╗ "
echo "  ██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔══██╗"
echo "  ██████╔╝███████║██████╔╝█████╗  ██████╔╝"
echo "  ██╔═══╝ ██╔══██║██╔═══╝ ██╔══╝  ██╔══██╗"
echo "  ██║     ██║  ██║██║     ███████╗██║  ██║"
echo "  ╚═╝     ╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝ DIGEST"
echo ""
echo "  Setting up PaperDigest..."
echo ""

# 1. Create conda env (skip if it already exists)
if ! conda env list | grep -q "^${ENV_NAME} "; then
  echo "→ Creating conda environment '${ENV_NAME}' (Python 3.11)..."
  conda create -n "$ENV_NAME" python=3.11 -y
else
  echo "→ Conda env '${ENV_NAME}' already exists"
fi

# 2. Activate
eval "$(conda shell.bash hook)"
conda activate "$ENV_NAME"

# 3. Install Python dependencies
echo "→ Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# 4. Clone paper-to-notebook into vendor/
if [ ! -d "vendor/paper-to-notebook" ]; then
  echo "→ Cloning paper-to-notebook into vendor/..."
  mkdir -p vendor
  git clone --depth=1 https://github.com/VizuaraAI/paper-to-notebook.git vendor/paper-to-notebook
  pip install -r vendor/paper-to-notebook/requirements.txt -q 2>/dev/null || true
  pip install -r vendor/paper-to-notebook/requirements.web.txt -q 2>/dev/null || true
  echo "✓ paper-to-notebook ready at vendor/paper-to-notebook/"
else
  echo "→ vendor/paper-to-notebook already exists, skipping clone"
fi

# 5. Clone PaperBanana into vendor/
if [ ! -d "vendor/paperbanana" ]; then
  echo "→ Cloning PaperBanana into vendor/..."
  mkdir -p vendor
  git clone --depth=1 https://github.com/llmsresearch/paperbanana.git vendor/paperbanana
  echo "✓ PaperBanana ready at vendor/paperbanana/"
else
  echo "→ vendor/paperbanana already exists, skipping clone"
fi

# 6. Set up .env
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  ACTION REQUIRED: Edit .env and add your Google API key"
  echo ""
  echo "  GOOGLE_API_KEY → https://aistudio.google.com/app/apikey"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
  echo "→ .env already exists"
fi

# 7. Create outputs dir
mkdir -p outputs

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your GOOGLE_API_KEY"
echo "  2. conda activate ${ENV_NAME}"
echo "  3. cd backend && uvicorn main:app --reload --port 8000"
echo "  4. Open http://localhost:8000"
echo ""
