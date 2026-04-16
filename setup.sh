#!/bin/bash

# Bureaucracy Hacker - One-Step Setup Script

echo "🚀 Bureaucracy Hacker Setup"
echo "=============================="
echo ""

# Check Python version
echo "Checking Python..."
python3 --version

# Install backend dependencies
echo ""
echo "📦 Installing backend dependencies..."
cd backend
pip install -r requirements.txt -q

# Copy .env template
echo ""
echo "📝 Creating .env file..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "✅ .env created. Edit it to add your ANTHROPIC_API_KEY"
else
    echo "✅ .env already exists"
fi

cd ..

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "  1. Edit backend/.env and add your ANTHROPIC_API_KEY"
echo "  2. Run: python backend/main.py     (Terminal 1)"
echo "  3. Run: python -m http.server 8000 (Terminal 2)"
echo "  4. Visit: http://localhost:8000"
echo ""
