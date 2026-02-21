#!/bin/bash
set -e

echo "🤖 Rasa Manager - Setup"
echo "========================"

# Verifica Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 não encontrado. Instale Python 3.9+"
    exit 1
fi

# Verifica Rasa
if ! command -v rasa &> /dev/null; then
    echo "⚠️  Rasa não encontrado. Instalando..."
    pip install rasa==3.6.20
fi

# Instala dependências do manager
echo "📦 Instalando dependências do backend..."
pip install -r requirements.txt

# Cria estrutura de dados se não existir
mkdir -p rasa_project/data rasa_project/models

echo ""
echo "✅ Setup concluído!"
echo ""
echo "Para iniciar o Rasa Manager:"
echo "  python server.py"
echo ""
echo "Acesse: http://localhost:8000"
echo ""
echo "Para rodar via Docker:"
echo "  docker-compose up --build"
