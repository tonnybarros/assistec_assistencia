#!/usr/bin/env bash
set -euo pipefail

# Caminho do módulo (ajuste se necessário)
MOD_DIR="/opt/odoo18/extra-addons/assistec_assistencia"
DEST="$MOD_DIR/static/description"

echo ">> Criando pasta destino: $DEST"
mkdir -p "$DEST"

echo ">> Descompactando screenshots para $DEST"
unzip -o assistec_assistencia_screenshots.zip -d "$DEST"

echo ">> Otimizando imagens (requer imagemagick + pngquant)"
if command -v mogrify >/dev/null 2>&1; then
  mogrify -strip -resize 1600x1600\> -quality 82 "$DEST"/*.png || true
else
  echo "   (mogrify não encontrado; pulei esta etapa)"
fi
if command -v pngquant >/dev/null 2>&1; then
  pngquant --quality=65-80 --ext .png --force "$DEST"/*.png || true
else
  echo "   (pngquant não encontrado; pulei esta etapa)"
fi

echo ">> Acrescentando snippet de README"
SNIP="$MOD_DIR/README_SNIPPET.md"
cat > "$SNIP" <<'EOF_README'
## Telas

### Lista de Ordens de Serviço
![Lista de OS](static/description/ordens-servico-lista.png)

### Dashboard (Painel)
![Dashboard](static/description/painel-dashboard.png)

### Gráficos de Ordens de Serviço
![Gráficos de OS](static/description/ordens-servico-graficos.png)

### Dashboard Financeiro
![Dashboard Financeiro](static/description/financeiro-dashboard.png)

### Formas de Pagamento
![Formas de Pagamento](static/description/financeiro-formas-pagamento-lista.png)

### Regras de Descontos
![Regras de Descontos](static/description/financeiro-regras-descontos-lista.png)

### Comissões Calculadas
![Comissões Calculadas](static/description/comissoes-calculadas-lista.png)

### Aparelhos (Cadastro)
![Aparelhos](static/description/configuracao-aparelhos-lista.png)

### Serviços (Cadastro e Preço)
![Serviços](static/description/configuracao-servicos-lista.png)

### Configuração de Situações (Etapas)
![Configuração de Situações](static/description/configuracao-situacoes-lista.png)

### Configurações de Assistência (Definições)
![Configurações de Assistência](static/description/configuracao-assistencia-definicoes.png)

### Webhook (Automatizações / n8n)
![Webhook da Assistência](static/description/configuracao-webhook-assistencia.png)

### Impressão de Comprovantes
![Impressão de Comprovantes](static/description/configuracao-impressoes-comprovantes.png)
EOF_README

echo ">> Git add/commit/push (se o repo já estiver inicializado)"
if [ -d "$MOD_DIR/.git" ]; then
  git -C "$MOD_DIR" add static/description/*.png README_SNIPPET.md || true
  git -C "$MOD_DIR" commit -m "docs: adiciona screenshots do módulo (batch)" || true
  # push pode ser automático via seu timer; executar manualmente se quiser:
  # git -C "$MOD_DIR" push
else
  echo "   (Repo Git não encontrado em $MOD_DIR — pulei commit/push)"
fi

echo ">> Feito."
