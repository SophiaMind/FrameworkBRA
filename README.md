# 🤖 Rasa Manager

Interface gráfica completa para gerenciar bots Rasa — crie, treine, teste e publique no Docker Hub.

---

## ✨ Funcionalidades

| Seção | O que faz |
|-------|-----------|
| 🧠 NLU / Intents | Editor visual de intents + editor YAML raw |
| 📖 Stories / Rules | Edição de stories e rules |
| 💬 Responses | Visualiza e edita respostas no domain.yml |
| 🌐 Domain | Editor completo do domain.yml |
| ⚙️ Pipeline | config.yml + credentials.yml |
| 🔌 Endpoints | endpoints.yml |
| 🚀 Treinar | Roda `rasa train` com log em tempo real |
| 💬 Chat | Inicia servidor Rasa e testa o bot |
| 🐳 Docker | Build + push para Docker Hub |

---

## 🚀 Como usar (local)

### Pré-requisitos
- Python 3.9+
- Rasa 3.6.x (`pip install rasa==3.6.20`)
- Docker (para build/push)

### Instalação

```bash
git clone <seu-repo>
cd rasa-manager
chmod +x setup.sh
./setup.sh
```

### Iniciar

```bash
python server.py
```

Acesse: **http://localhost:8000**

---

## 🐳 Workflow Docker

### 1. Treine o modelo
Na interface → **Treinar** → clique em **Iniciar Treinamento**

### 2. Teste o bot
Na interface → **Chat** → **Iniciar Servidor** → converse com o bot

### 3. Gere a imagem Docker
Na interface → **Docker** → preencha os dados do Docker Hub → **Build + Push**

### 4. Use na sua pipeline

```bash
# Baixa e roda a imagem
docker pull seu-usuario/seu-bot:latest
docker run -p 5005:5005 seu-usuario/seu-bot:latest
```

```yaml
# docker-compose.yml do seu projeto
services:
  rasa-bot:
    image: seu-usuario/seu-bot:latest
    ports:
      - "5005:5005"
    restart: unless-stopped
```

```yaml
# GitHub Actions
- name: Deploy Rasa Bot
  run: |
    echo "${{ secrets.DOCKER_TOKEN }}" | docker login -u "${{ secrets.DOCKER_USER }}" --password-stdin
    docker pull ${{ secrets.DOCKER_USER }}/meu-bot:latest
    docker stop rasa-bot || true
    docker rm rasa-bot || true
    docker run -d --name rasa-bot -p 5005:5005 --restart unless-stopped \
      ${{ secrets.DOCKER_USER }}/meu-bot:latest
```

---

## 🐳 Rodar via Docker (o manager em si)

```bash
docker-compose up --build
```

> Requer Docker socket montado para poder fazer builds de dentro do container.

---

## 📁 Estrutura

```
rasa-manager/
├── server.py              # FastAPI backend
├── requirements.txt
├── frontend/
│   └── index.html         # SPA completa (HTML/JS puro)
├── rasa_project/          # Seu projeto Rasa
│   ├── data/
│   │   ├── nlu.yml
│   │   ├── stories.yml
│   │   └── rules.yml
│   ├── domain.yml
│   ├── config.yml
│   ├── endpoints.yml
│   └── models/            # Modelos treinados
├── Dockerfile.manager     # Para rodar o manager em Docker
├── Dockerfile.bot         # Gerado automaticamente no build
├── docker-compose.yml
└── setup.sh
```

---

## 🔌 API REST

O backend expõe uma API completa:

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/files/{path}` | Lê arquivo do projeto Rasa |
| POST | `/api/files/{path}` | Salva arquivo |
| GET | `/api/models` | Lista modelos treinados |
| POST | `/api/train` | Inicia treinamento |
| GET | `/api/train/status` | Status do treinamento |
| GET | `/api/train/logs` | SSE com logs em tempo real |
| POST | `/api/server/start` | Inicia servidor Rasa |
| POST | `/api/server/stop` | Para servidor Rasa |
| POST | `/api/chat` | Envia mensagem para o bot |
| POST | `/api/docker/build` | Build + push Docker |
| GET | `/api/docker/logs` | SSE com logs do Docker |

---

## 💡 Dicas

- **Token Docker Hub**: Crie em hub.docker.com → Account Settings → Security → New Access Token
- **Múltiplos bots**: Copie a pasta `rasa_project/` com um nome diferente por bot
- **CI/CD**: Use a variável `DOCKER_TOKEN` e `DOCKER_USER` no seu secrets
