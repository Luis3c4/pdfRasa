    # Comandos para levantar el proyecto

## Primera vez (instalación)

```bash
# Instalar bitsandbytes para cuantización Q4
cd /home/luis/Project/rasa/pdfbot
source .venv/bin/activate
uv pip install bitsandbytes
```

```bash
# Agregar variable de entorno permanente
echo 'export VLLM_API_KEY="not-needed"' >> ~/.bashrc
source ~/.bashrc
```

---

## Levantar el proyecto (cada vez)

Abrir **4 terminales** y ejecutar en orden:

### Terminal 1 — LLM (Qwen2.5 7B)
```bash
cd /home/luis/Project/rasa/pdfbot
source .venv/bin/activate

vllm serve "Qwen/Qwen2.5-7B-Instruct" \
  --quantization bitsandbytes \
  --load-format bitsandbytes \
  --gpu-memory-utilization 0.86 \
  --max-model-len 4096 \
  --enforce-eager \
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
source ../.venv/bin/activate   # ajustar si el venv de rasa está en otro lugar
export VLLM_API_KEY="not-needed"

rasa train    # solo cuando haya cambios en flows/domain/config
rasa inspect  # levanta el bot con UI de debug
```

### Terminal 4 — Actions server (si usas acciones custom)
```bash
cd /home/luis/Project/rasa/pdfRasa
source ../.venv/bin/activate
export VLLM_API_KEY="not-needed"

rasa run actions
```

---

## VRAM estimada

| Servicio | Puerto | VRAM |
|---|---|---|
| Qwen2.5 7B Q4 | 8000 | ~4.5 GB |
| bge-m3 embeddings | 8001 | ~0.5 GB |
| **Total** | | **~5.0 GB / 6.88 GB** |

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
