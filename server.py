import os
import subprocess
import asyncio
import signal
import json
import glob
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime

import yaml
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Rasa Manager", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Config ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
RASA_PROJECT = BASE_DIR / "rasa_project"
MODELS_DIR = RASA_PROJECT / "models"

# Estado global
training_status = {"running": False, "logs": [], "last_model": None}
rasa_server_process: Optional[subprocess.Popen] = None
rasa_server_port = 5005


# ── Models ───────────────────────────────────────────────────────────────────
class FileContent(BaseModel):
    content: str


class ChatMessage(BaseModel):
    message: str
    sender: str = "user"


class DockerConfig(BaseModel):
    image_name: str
    tag: str = "latest"
    dockerhub_user: str
    dockerhub_token: str
    push: bool = True


class RasaServerConfig(BaseModel):
    model: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────
def read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_models():
    models = []
    if MODELS_DIR.exists():
        for f in sorted(MODELS_DIR.glob("*.tar.gz"), key=os.path.getmtime, reverse=True):
            stat = f.stat()
            models.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(stat.st_size / 1024 / 1024, 2),
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
    return models


# ── File Endpoints ────────────────────────────────────────────────────────────
@app.get("/api/files/{file_path:path}")
def get_file(file_path: str):
    path = RASA_PROJECT / file_path
    if not path.exists():
        raise HTTPException(404, f"Arquivo não encontrado: {file_path}")
    return {"content": read_file(path), "path": file_path}


@app.post("/api/files/{file_path:path}")
def save_file(file_path: str, body: FileContent):
    path = RASA_PROJECT / file_path
    # Validação básica de YAML para arquivos .yml
    if not body.content.strip():
        raise HTTPException(400, "Conteúdo do arquivo não pode ser vazio")
    write_file(path, body.content)
    return {"ok": True, "message": f"Arquivo {file_path} salvo com sucesso"}


@app.get("/api/files-list")
def list_files():
    files = []
    for p in RASA_PROJECT.rglob("*.yml"):
        rel = p.relative_to(RASA_PROJECT)
        if "models" not in str(rel) and ".rasa" not in str(rel):
            files.append(str(rel))
    return {"files": sorted(files)}


# ── Training ──────────────────────────────────────────────────────────────────
@app.post("/api/train")
async def train_model(background_tasks: BackgroundTasks):
    if training_status["running"]:
        raise HTTPException(409, "Treinamento já em andamento")
    training_status["running"] = True
    training_status["logs"] = []
    background_tasks.add_task(_run_training)
    return {"ok": True, "message": "Treinamento iniciado"}


async def _run_training():
    try:
        proc = await asyncio.create_subprocess_exec(
            "rasa", "train",
            "--domain", str(RASA_PROJECT / "domain.yml"),
            "--data", str(RASA_PROJECT / "data"),
            "--config", str(RASA_PROJECT / "config.yml"),
            "--out", str(MODELS_DIR),
            "--fixed-model-name", f"model_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            cwd=str(RASA_PROJECT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            decoded = line.decode("utf-8", errors="replace").rstrip()
            training_status["logs"].append(decoded)

        await proc.wait()
        training_status["running"] = False

        # Pega último modelo
        models = get_models()
        if models:
            training_status["last_model"] = models[0]["name"]
            training_status["logs"].append(f"\n✅ Modelo salvo: {models[0]['name']}")
        else:
            training_status["logs"].append("\n❌ Nenhum modelo encontrado após treinamento")
    except Exception as e:
        training_status["running"] = False
        training_status["logs"].append(f"\n❌ Erro: {str(e)}")


@app.get("/api/train/status")
def train_status():
    return training_status


@app.get("/api/train/logs")
def train_logs_stream():
    """SSE stream dos logs de treinamento"""
    def generate():
        last_idx = 0
        while True:
            logs = training_status["logs"]
            if len(logs) > last_idx:
                for line in logs[last_idx:]:
                    yield f"data: {json.dumps({'log': line})}\n\n"
                last_idx = len(logs)
            if not training_status["running"] and last_idx >= len(logs):
                yield f"data: {json.dumps({'done': True})}\n\n"
                break
    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Models ────────────────────────────────────────────────────────────────────
@app.get("/api/models")
def list_models():
    return {"models": get_models()}


@app.delete("/api/models/{model_name}")
def delete_model(model_name: str):
    path = MODELS_DIR / model_name
    if not path.exists():
        raise HTTPException(404, "Modelo não encontrado")
    path.unlink()
    return {"ok": True}


# ── Rasa Server (para testes de chat) ─────────────────────────────────────────
@app.post("/api/server/start")
async def start_rasa_server(config: RasaServerConfig):
    global rasa_server_process

    if rasa_server_process and rasa_server_process.poll() is None:
        return {"ok": True, "message": "Servidor já rodando", "port": rasa_server_port}

    models = get_models()
    if not models and not config.model:
        raise HTTPException(400, "Nenhum modelo disponível. Treine primeiro.")

    model_path = str(MODELS_DIR / (config.model or models[0]["name"]))

    cmd = [
        "rasa", "run",
        "--model", model_path,
        "--enable-api",
        "--cors", "*",
        "--port", str(rasa_server_port),
        "--endpoints", str(RASA_PROJECT / "endpoints.yml"),
    ]

    rasa_server_process = subprocess.Popen(
        cmd,
        cwd=str(RASA_PROJECT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    await asyncio.sleep(3)  # Aguarda inicialização
    return {"ok": True, "message": "Servidor iniciado", "port": rasa_server_port}


@app.post("/api/server/stop")
def stop_rasa_server():
    global rasa_server_process
    if rasa_server_process and rasa_server_process.poll() is None:
        rasa_server_process.terminate()
        rasa_server_process = None
        return {"ok": True, "message": "Servidor parado"}
    return {"ok": False, "message": "Servidor não estava rodando"}


@app.get("/api/server/status")
def server_status():
    global rasa_server_process
    running = rasa_server_process is not None and rasa_server_process.poll() is None
    return {"running": running, "port": rasa_server_port if running else None}


# ── Chat ──────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(msg: ChatMessage):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"http://localhost:{rasa_server_port}/webhooks/rest/webhook",
                json={"sender": msg.sender, "message": msg.message}
            )
            return {"responses": resp.json()}
    except Exception as e:
        raise HTTPException(503, f"Servidor Rasa não disponível: {str(e)}\n\nInicie o servidor primeiro em 'Chat > Iniciar Servidor'")


# ── Docker ────────────────────────────────────────────────────────────────────
@app.post("/api/docker/build")
async def docker_build(config: DockerConfig, background_tasks: BackgroundTasks):
    models = get_models()
    if not models:
        raise HTTPException(400, "Nenhum modelo treinado. Treine primeiro.")

    model_file = models[0]["name"]
    full_image = f"{config.dockerhub_user}/{config.image_name}:{config.tag}"

    # Gera Dockerfile dinâmico
    dockerfile_content = f"""FROM rasa/rasa:3.6.20-full

WORKDIR /app

USER root

# Copia modelo treinado
COPY rasa_project/models/{model_file} /app/models/{model_file}

# Copia configurações
COPY rasa_project/domain.yml /app/domain.yml
COPY rasa_project/config.yml /app/config.yml
COPY rasa_project/endpoints.yml /app/endpoints.yml
COPY rasa_project/data /app/data

USER 1001

EXPOSE 5005

ENTRYPOINT ["rasa", "run", "--model", "/app/models/{model_file}", "--enable-api", "--cors", "*", "--port", "5005"]
"""

    dockerfile_path = BASE_DIR / "Dockerfile.bot"
    dockerfile_path.write_text(dockerfile_content)

    background_tasks.add_task(
        _run_docker_build,
        full_image,
        config.dockerhub_user,
        config.dockerhub_token,
        config.push
    )

    return {"ok": True, "message": f"Build iniciado para {full_image}", "image": full_image}


docker_build_status = {"running": False, "logs": [], "image": None, "success": False}


async def _run_docker_build(image: str, user: str, token: str, push: bool):
    global docker_build_status
    docker_build_status = {"running": True, "logs": [], "image": image, "success": False}
    BASE_DIR_str = str(BASE_DIR)

    try:
        # Build
        docker_build_status["logs"].append(f"🔨 Iniciando build: {image}")
        proc = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", image, "-f", "Dockerfile.bot", ".",
            cwd=BASE_DIR_str,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            docker_build_status["logs"].append(line.decode("utf-8", errors="replace").rstrip())
        await proc.wait()

        if proc.returncode != 0:
            docker_build_status["logs"].append("❌ Build falhou!")
            docker_build_status["running"] = False
            return

        docker_build_status["logs"].append("✅ Build concluído!")

        if push:
            # Login
            docker_build_status["logs"].append("🔐 Fazendo login no Docker Hub...")
            login_proc = await asyncio.create_subprocess_exec(
                "docker", "login", "-u", user, "--password-stdin",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await login_proc.communicate(input=token.encode())
            docker_build_status["logs"].append(stdout.decode("utf-8", errors="replace").rstrip())

            if login_proc.returncode != 0:
                docker_build_status["logs"].append("❌ Login falhou!")
                docker_build_status["running"] = False
                return

            # Push
            docker_build_status["logs"].append(f"📤 Enviando para Docker Hub: {image}")
            push_proc = await asyncio.create_subprocess_exec(
                "docker", "push", image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async for line in push_proc.stdout:
                docker_build_status["logs"].append(line.decode("utf-8", errors="replace").rstrip())
            await push_proc.wait()

            if push_proc.returncode == 0:
                docker_build_status["logs"].append(f"\n✅ Imagem publicada com sucesso!")
                docker_build_status["logs"].append(f"🐳 Use: docker pull {image}")
                docker_build_status["success"] = True
            else:
                docker_build_status["logs"].append("❌ Push falhou!")
        else:
            docker_build_status["success"] = True

    except Exception as e:
        docker_build_status["logs"].append(f"❌ Erro: {str(e)}")
    finally:
        docker_build_status["running"] = False


@app.get("/api/docker/status")
def docker_status():
    return docker_build_status


@app.get("/api/docker/logs")
def docker_logs_stream():
    def generate():
        last_idx = 0
        while True:
            logs = docker_build_status["logs"]
            if len(logs) > last_idx:
                for line in logs[last_idx:]:
                    yield f"data: {json.dumps({'log': line})}\n\n"
                last_idx = len(logs)
            if not docker_build_status["running"] and last_idx >= len(logs):
                yield f"data: {json.dumps({'done': True, 'success': docker_build_status['success']})}\n\n"
                break
    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Serve frontend ────────────────────────────────────────────────────────────
app.mount("/", StaticFiles(directory=str(BASE_DIR / "frontend"), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
