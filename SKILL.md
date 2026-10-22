---
name: hydracode
description: Delega tareas a otros modelos (Gemini, Antigravity, Codex, Groq, Ollama, etc.) con fallback automático cuando se acaba una cuota. Úsalo para leer/resumir, boilerplate, tareas mecánicas, segundas opiniones de plan o revisión, y para ver el consumo de tokens.
---

# hydracode

CLI: `hydracode <rol> "instrucción" [--private] [< archivo]` (instalado por `install.sh`). Imprime solo el texto; el proveedor usado sale por stderr (`[via X]`). Exit 1 con `ROUTER_FAILED ...` si toda la cadena falla: en ese caso hazlo tú sin avisar.

## Roles
- `leer`: resumir/explicar archivos largos, extraer datos. Modelos gratis primero.
- `mecanico`: boilerplate, conversiones de formato, regex, SQL suelto, traducciones.
- `ask`: preguntas generales de programación (sustituye al antiguo `ask`).
- `planear`: plan o segunda opinión de arquitectura (privado: Codex/Claude).
- `revisar`: revisar un diff o archivo con un modelo distinto al que escribió el código (privado).

`hydracode roles` muestra las cadenas; `hydracode status` el consumo (`gemini-lite 3% · codex ⏳quota`).

## Privacidad
Los proveedores gratis pueden entrenar con lo que reciben. Añade `--private` siempre que la entrada contenga código del proyecto, datos de clientes, IPs de red o secretos; así solo se usan proveedores marcados "apto privado". Nunca envíes `.env`, keys ni tokens.

## No delegar
Edits a código existente, debugging, decisiones que dependen del contexto de la sesión, comandos con efectos (deploy, DB, git). Valida la salida antes de usarla y di en una línea que vino de hydracode.

## Portal
`hydracode portal` abre el servidor en http://127.0.0.1:4190 (conectar proveedores, guardar keys, probar, ordenar cadenas, ver cooldowns). Las keys van a `~/.config/hydracode/secrets.json` (600) y nunca se muestran de vuelta.
