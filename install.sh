#!/usr/bin/env bash
# Hydracode · by carlosplata.dev · instalador
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${HYDRACODE_SKILL_DIR:-$HOME/.claude/skills/hydracode}"
BIN="${HYDRACODE_BIN_DIR:-$HOME/.local/bin}"
MODEL="qwen2.5-coder:1.5b"
OLLAMA=1; LINK=0
for a in "$@"; do
  case "$a" in
    --no-ollama) OLLAMA=0 ;;
    --link) LINK=1 ;;
    -h|--help) echo "uso: ./install.sh [--no-ollama] [--link]"; exit 0 ;;
    *) echo "opción desconocida: $a" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "Hydracode necesita python3 (3.9+)." >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "Se requiere Python 3.9 o superior." >&2; exit 1; }

mkdir -p "$(dirname "$DEST")" "$BIN"
if [ "$LINK" = 1 ]; then
  rm -rf "$DEST"; ln -s "$SRC" "$DEST"
else
  rm -rf "$DEST"; mkdir -p "$DEST"
  cp "$SRC"/{hydracode.py,portal.py,portal.html,defaults.json,presets.json,catalog.json,SKILL.md} "$DEST"/
fi
chmod +x "$DEST/hydracode.py"
ln -sf "$DEST/hydracode.py" "$BIN/hydracode"
echo "✓ Hydracode instalado en $DEST"

if [ "$OLLAMA" = 1 ]; then
  if ! command -v ollama >/dev/null; then
    echo "→ Instalando Ollama (modelos locales, sin cuota)…"
    if [ "$(uname)" = Darwin ] && command -v brew >/dev/null; then
      brew install ollama
    elif [ "$(uname)" = Linux ]; then
      curl -fsSL https://ollama.com/install.sh | sh
    else
      echo "! Instala Ollama desde https://ollama.com/download y vuelve a correr con ollama ya instalado." >&2
    fi
  fi
  if command -v ollama >/dev/null; then
    if ! curl -fs http://localhost:11434/api/tags >/dev/null 2>&1; then
      echo "→ Iniciando el servidor de Ollama…"
      (brew services start ollama >/dev/null 2>&1 || nohup ollama serve >/dev/null 2>&1 &)
      for _ in 1 2 3 4 5 6 7 8; do curl -fs http://localhost:11434/api/tags >/dev/null 2>&1 && break; sleep 1; done
    fi
    echo "→ Descargando el modelo $MODEL (~1 GB)…"
    ollama pull "$MODEL" || echo "! No se pudo descargar el modelo; hazlo luego con: ollama pull $MODEL" >&2
  fi
else
  echo "· Ollama omitido (--no-ollama). Hydracode funciona sin él, pero sin fallback local."
fi

case ":$PATH:" in *":$BIN:"*) ;; *) echo "! Agrega $BIN a tu PATH:  export PATH=\"$BIN:\$PATH\"" ;; esac
echo "Listo. Prueba:  hydracode --version   y   hydracode portal"
