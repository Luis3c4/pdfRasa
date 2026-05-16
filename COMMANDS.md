    # Comandos para levantar el proyecto

## Primera vez (instalación)

```bash
# Agregar variable de entorno permanente
echo 'export VLLM_API_KEY="not-needed"' >> ~/.bashrc
source ~/.bashrc
```

---

## Levantar el proyecto (cada vez)

Abrir **4 terminales** y ejecutar en orden:

### Terminal 1 — LLM (Qwen2.5 3B AWQ)
```bash
cd /home/luis/Project/rasa/pdfbot
source .venv/bin/activate

vllm serve "Qwen/Qwen2.5-3B-Instruct-AWQ" \
  --quantization awq \
  --dtype half \
  --gpu-memory-utilization 0.75 \
  --max-model-len 2048 \
  --port 8000
```
> Esperar hasta ver: `Application startup complete.`

### Terminal 2 — Embeddings (bge-m3)
```bash
cd /home/luis/Project/rasa/pdfbot
source .venv/bin/activate

vllm serve "BAAI/bge-m3" \
  --gpu-memory-utilization 0.10 \
  --port 8001
```
> Esperar hasta ver: `Application startup complete.`

### Terminal 3 — Rasa
```bash
cd /home/luis/Project/rasa/pdfRasa
source .venv/bin/activate   # ajustar si el venv de rasa está en otro lugar
set -a && source .env && set +a
rasa train    # cuando haya cambios en flows/domain/config
rasa inspect  # primero: levanta el bot con UI de debug (queda corriendo)
# al terminar inspect (Ctrl+C), recién ejecutar:
rasa run --enable-api --cors "*"
```

### Terminal 4 — Actions server (si usas acciones custom)
```bash
cd /home/luis/Project/rasa/pdfRasa
source .venv/bin/activate
set -a && source .env && set +a

rasa run actions
```

### Terminal 5 — ngrok (para Chatwoot en EC2)
```bash
ngrok http 5005
```

Copiar la URL HTTPS que te da ngrok (ejemplo: `https://xxxx-xx-xx-xx-xx.ngrok-free.app`) y en Chatwoot configurar el webhook del bot a:

`https://TU_URL_NGROK/webhooks/chatwoot/webhook`

No pongas esa URL en `CHATWOOT_URL` del archivo `.env`. `CHATWOOT_URL` debe seguir apuntando al dominio base de Chatwoot, por ejemplo:

`CHATWOOT_URL=https://limbert.site`

> Nota: para integrar Chatwoot con Rasa solo necesitas exponer el puerto 5005 (Rasa).

### ¿También necesito ngrok para Actions?

En este proyecto, normalmente **no**. Rasa llama a Actions por red interna/local.

Solo abre un segundo túnel si tu Rasa no puede llegar al Actions local por `localhost` (por ejemplo, Rasa en otra máquina o contenedor aislado):

```bash
ngrok http 5055
```

Y en ese caso configura `action_endpoint.url` apuntando al webhook público de Actions.

---

## VRAM estimada

| Servicio | Puerto | VRAM |
|---|---|---|
| Qwen2.5 3B AWQ | 8000 | ~2.0 GB |
| bge-m3 embeddings | 8001 | ~0.6 GB |
| **Total** | | **~2.6 GB / 8.15 GB** |

---

## Comandos útiles

```bash
# Verificar que los servidores están corriendo
curl http://localhost:8000/v1/models
curl http://localhost:8001/v1/models

# Entrenar sin levantar el inspector
rasa train

# Probar por consola
rasa shell

# Correr tests e2e
rasa test e2e e2e_tests/
```
