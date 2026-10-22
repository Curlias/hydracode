# Hydracode

Router de modelos con fallback automático para Claude Code. Delega lectura, tareas mecánicas, planes y revisiones a otros modelos (Gemini, Groq, OpenRouter, Antigravity, Codex, Ollama local…) y cambia solo al siguiente cuando uno se queda sin cuota.

By [carlosplata.dev](https://carlosplata.dev)

## Instalar

```bash
git clone https://github.com/Curlias/hydracode.git
cd hydracode && ./install.sh
```

Por defecto instala también [Ollama](https://ollama.com) y descarga `qwen2.5-coder:7b` (~4.7 GB) como respaldo local. Con menos de 16 GB de RAM baja solo a `3b` (~1.9 GB), y con menos de 8 GB a `1.5b`; `HYDRACODE_MODEL=... ./install.sh` fuerza uno como respaldo local sin cuota. Usa `./install.sh --no-ollama` para omitirlo. En Linux el instalador usa el script oficial de Ollama (`curl | sh`).

Para no trabar el equipo, Ollama se llama con su API nativa: el modelo se descarga de la RAM a los 30 s (`keep_alive`), el contexto se limita a 4096 y, si hay menos de `min_free_gb` de RAM libre (2.5 por defecto), hydracode se salta Ollama y pasa a la siguiente IA. Los tres valores se editan en el portal (Avanzado).

Requiere Python 3.9+, sin dependencias externas.

## Uso

```bash
hydracode portal                       # portal local en http://127.0.0.1:4190
hydracode leer "resume esto" < archivo
hydracode planear "plan para X" --private
hydracode status                       # consumo y pausas por proveedor
```

El portal conecta cada servicio con un clic: login por navegador (OpenRouter, ChatGPT/Codex, Claude) o «conseguir key» y «pegar y conectar» (Gemini, Groq, xAI). Las keys se guardan en `~/.config/hydracode/secrets.json` (permisos 600) y nunca se muestran de vuelta.

## Roles

`leer`, `mecanico`, `ask`, `planear` y `revisar`, cada uno con una cadena de proveedores editable desde el portal. `--private` limita la tarea a proveedores marcados «apto para código privado» (los gratis pueden entrenar con tus datos).

Se instala además como skill de Claude Code en `~/.claude/skills/hydracode`.

## Pruebas

```bash
python3 -m unittest discover -s tests
```

MIT © Carlos Plata
