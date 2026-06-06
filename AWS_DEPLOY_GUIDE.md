# pdfRasa en AWS (instancia existente con Chatwoot)

## 1. Entrar al servidor

```bash
ssh -i /ruta/tu-key.pem ubuntu@TU_ELASTIC_IP
```

## 2. Instalar dependencias base

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git curl nginx python3 python3-venv python3-pip certbot python3-certbot-nginx
```

## 3. Descargar proyecto

```bash
mkdir -p /home/ubuntu/apps
cd /home/ubuntu/apps
git clone https://github.com/TU-USUARIO/TU-REPO.git
cd /home/ubuntu/apps/TU-REPO/pdfRasa
```

## 4. Crear entorno Python e instalar paquetes

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 5. Crear archivo .env de produccion

```bash
cat > /home/ubuntu/apps/TU-REPO/pdfRasa/.env << 'EOF'
RASA_PRO_LICENSE_KEY=REEMPLAZAR
OPENAI_API_KEY=not-needed
VLLM_API_KEY=not-needed
NVIDIA_API_KEY=REEMPLAZAR

CHATWOOT_URL=https://chat.limbert.site
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_ACCESS_TOKEN=REEMPLAZAR

YAPE_NUMBER=923252274
EOF
```

## 6. Cargar variables y entrenar modelo

```bash
cd /home/ubuntu/apps/TU-REPO/pdfRasa
source .venv/bin/activate
set -a && source .env && set +a
rasa train
```

## 7. Probar manualmente (opcional)

Terminal 1:

```bash
cd /home/ubuntu/apps/TU-REPO/pdfRasa
source .venv/bin/activate
set -a && source .env && set +a
rasa run actions --port 5055
```

Terminal 2:

```bash
cd /home/ubuntu/apps/TU-REPO/pdfRasa
source .venv/bin/activate
set -a && source .env && set +a
rasa run --enable-api --cors "*" --port 5005
```

Health check:

```bash
curl http://127.0.0.1:5005/status
```

## 8. Crear servicio systemd para Actions

```bash
sudo tee /etc/systemd/system/rasa-actions.service > /dev/null << 'EOF'
[Unit]
Description=Rasa Actions Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/apps/TU-REPO/pdfRasa
EnvironmentFile=/home/ubuntu/apps/TU-REPO/pdfRasa/.env
ExecStart=/home/ubuntu/apps/TU-REPO/pdfRasa/.venv/bin/rasa run actions --port 5055
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

## 9. Crear servicio systemd para Rasa API

```bash
sudo tee /etc/systemd/system/rasa.service > /dev/null << 'EOF'
[Unit]
Description=Rasa Server
After=network.target rasa-actions.service
Requires=rasa-actions.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/apps/TU-REPO/pdfRasa
EnvironmentFile=/home/ubuntu/apps/TU-REPO/pdfRasa/.env
ExecStart=/home/ubuntu/apps/TU-REPO/pdfRasa/.venv/bin/rasa run --enable-api --cors "*" --port 5005
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

## 10. Activar servicios

```bash
sudo systemctl daemon-reload
sudo systemctl enable rasa-actions
sudo systemctl enable rasa
sudo systemctl start rasa-actions
sudo systemctl start rasa
```

## 11. Ver estado y logs

```bash
sudo systemctl status rasa-actions --no-pager
sudo systemctl status rasa --no-pager
sudo journalctl -u rasa-actions -n 200 --no-pager
sudo journalctl -u rasa -n 200 --no-pager
```

## 12. Configurar Nginx para bot.limbert.site

```bash
sudo tee /etc/nginx/sites-available/pdfrasa > /dev/null << 'EOF'
server {
    listen 80;
    server_name bot.limbert.site;

    location / {
        proxy_pass http://127.0.0.1:5005;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
EOF
```

```bash
sudo ln -sf /etc/nginx/sites-available/pdfrasa /etc/nginx/sites-enabled/pdfrasa
sudo nginx -t
sudo systemctl reload nginx
```

## 13. SSL para bot.limbert.site

```bash
sudo certbot --nginx -d bot.limbert.site --redirect -m TU_EMAIL --agree-tos -n
```

```bash
curl -I https://bot.limbert.site/status
```

## 14. Webhook en Chatwoot

```text
https://bot.limbert.site/webhooks/chatwoot/webhook
```

## 15. Comandos de operacion diaria

Reiniciar:

```bash
sudo systemctl restart rasa-actions
sudo systemctl restart rasa
sudo systemctl reload nginx
```

Actualizar codigo y redeploy:

```bash
cd /home/ubuntu/apps/TU-REPO
git pull
cd /home/ubuntu/apps/TU-REPO/pdfRasa
source .venv/bin/activate
pip install -r requirements.txt
set -a && source .env && set +a
rasa train
sudo systemctl restart rasa-actions
sudo systemctl restart rasa
```
