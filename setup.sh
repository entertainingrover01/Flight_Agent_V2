#!/bin/bash

echo "Bureaucracy Hacker setup"
echo "========================"
echo

python3 --version

echo
echo "Installing backend dependencies..."
cd backend || exit 1
python3 -m pip install -r requirements.txt

echo
echo "Creating backend/.env from template if needed..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created backend/.env"
else
    echo "backend/.env already exists"
fi

cd .. || exit 1

echo
echo "Next steps:"
echo "  1. Add GOOGLE_API_KEY to backend/.env"
echo "  2. Add GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET if using Gmail scan"
echo "  3. Run backend: cd backend && ../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001"
echo "  4. Run frontend: python3 -m http.server 8000"
echo "  5. Open: http://localhost:8000"
