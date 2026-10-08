# EchoSing — Backlog MVP (Fase 1)

Cada historia se implementa así: mini-plan → aprobación → implementación con tests →
`ruff` / `mypy --strict` / `pytest` en verde → commit atómico.

## Decisiones de arquitectura

| Tema | Decisión |
|---|---|
| Alcance | Backend completo + cliente web mínimo (React). Móvil queda para después. |
| Persistencia | Solo PostgreSQL; letras y curvas F0 como JSONB (sin MongoDB). |
| Storage | Filesystem local detrás de una interfaz `StorageBackend` (migrable a S3). |
| Hardware | GPU NVIDIA local (RTX 5060 8 GB) para la ingesta. |
| Scoring | Híbrido: el navegador extrae F0 (YIN en AudioWorklet) y lo envía por WebSocket; el servidor corre DTW (numpy, en executor). Nunca viaja audio. |
| Usuarios | Sin auth en el MVP: sesiones anónimas con `player_name`. |
| Infra dev | Docker Desktop (WSL2) solo para Postgres + Redis. La API y el worker Celery (`--pool=solo`) corren nativos en Windows. |

## Stack

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async + asyncpg, Alembic,
  Celery + Redis, `uv`, Ruff (88 cols), `mypy --strict`, pytest + pytest-asyncio + httpx.
- **ML (cajas negras con wrappers):** Demucs v4 (`htdemucs`), Whisper
  (`word_timestamps=True`), CREPE (`torchcrepe`, hop 10 ms).
- **GPU:** RTX 5060 (Blackwell) → PyTorch ≥ 2.7 con wheels **cu128**. Con 8 GB de VRAM,
  un modelo por etapa y liberación explícita (`del`, `torch.cuda.empty_cache()`).
- **Web:** Vite + React + TypeScript, Web Audio API + AudioWorklet (YIN), Recharts.

## Prerrequisitos de la máquina (manuales)

1. Activar **SVM Mode** en el BIOS (solo esa opción). Necesario antes de US-0.2.
2. Verificar: `Get-CimInstance Win32_Processor | Select VirtualizationFirmwareEnabled` → `True`.
3. Instalar Docker Desktop (WSL2) y limitar RAM en `%UserProfile%\.wslconfig` (`memory=4GB`).
4. Instalar `uv` (instala Python 3.12). Necesario antes de US-0.1.
5. Instalar Node.js LTS (para E6).

## Estructura

```
EchoSing/
├─ backend/
│  ├─ app/
│  │  ├─ api/routes/   # routers delgados (solo HTTP/WS)
│  │  ├─ services/     # lógica de negocio
│  │  ├─ ml/           # wrappers Demucs/Whisper/CREPE (Protocols)
│  │  ├─ scoring/      # pitch utils + DTW + normalización (numpy)
│  │  ├─ workers/      # Celery app + tasks
│  │  ├─ db/           # modelos SQLAlchemy, sesión, repositorios
│  │  ├─ storage/      # StorageBackend + LocalStorage
│  │  ├─ schemas/      # modelos Pydantic (API e internos)
│  │  └─ core/         # config, logging
│  ├─ tests/           # unit/, integration/, fixtures/*.json
│  ├─ alembic/
│  └─ pyproject.toml
├─ web/
├─ docker-compose.yml
└─ docs/
```

---

## Hitos

1. **M1 – Base:** E0 + E1.
2. **M2 – Catálogo procesado:** E2 + E3.
3. **M3 – Scoring:** E4 + E5.
4. **M4 – Jugable:** E6.
5. **M5 – Práctica:** E7.

---

## E0 — Fundaciones

- [x] **US-0.1 Scaffolding del backend.** Proyecto FastAPI con `uv`, Ruff, mypy strict y pytest.
  *AC:* `GET /health` → 200; `ruff check`, `mypy --strict` y `pytest` pasan; `git init` +
  `.gitignore` (excluye audio, `storage/` y modelos).
- [x] **US-0.2 Config e infraestructura local.** `docker-compose` con Postgres y Redis;
  `Settings` con pydantic-settings; `.env.example`.
  *AC:* `/health` reporta el estado de DB y Redis.
- [x] **US-0.3 Pre-commit.** Hooks de ruff + mypy.
- [x] **US-0.4 Smoke test de GPU.** Grupo de dependencias `ml` (torch cu128, demucs,
  openai-whisper, torchcrepe) separado de las dependencias base. Script
  `scripts/check_gpu.py` que verifica CUDA y soporte sm_120.

## E1 — Dominio y persistencia

- [x] **US-1.1 Modelo de datos + Alembic.** Tablas `songs` (con `language`), `song_assets`,
  `song_analyses` (JSONB versionado, una versión `is_current` por canción),
  `ingestion_jobs`, `play_sessions` (referencia el `analysis_id` jugado), `line_scores`.
  *AC:* la migración inicial aplica y revierte; repositorios async testeados.
- [x] **US-1.2 Abstracción de storage.** `StorageBackend` (Protocol) + `LocalStorage` async.
- [x] **US-1.3 Formato de análisis.** Esquemas Pydantic `SongAnalysisData`, `LyricLine`,
  `Word`, `PitchCurve` (MIDI + confianza 0–100, curva global) +
  [analysis-format.md](analysis-format.md).

## E2 — Pipeline de ingesta

- [x] **US-2.1 Alta de canción (admin).** `POST /admin/songs` (protegido con
  `X-Admin-Token`) y comando CLI; crea la canción en estado PENDING y encola el job.
  Incluye la app Celery mínima y la interfaz `JobQueue` (adelantadas de US-2.6); la
  tarea `ingestion.run` es un placeholder hasta US-2.2–2.6.
- [x] **US-2.2 Separación de fuentes.** `SourceSeparator` → Demucs en subproceso
  (`vocals.flac` + `instrumental.mp3`), validación con `ffprobe` y `duration_ms`. CLI
  `run-stage separate`. Presets por canción (`songs.separation_preset`): `demucs`
  (htdemucs, 5 shifts, ~35 s, ~1.1 GB VRAM, default) y `roformer` (BS-RoFormer Viperx
  1297 vía audio-separator, ~160–180 s, ~3 GB VRAM).
- [x] **US-2.3 Transcripción.** `Transcriber` → Whisper `large-v3-turbo` (subproceso) con
  timestamps por palabra sobre `vocals.flac`; artefacto `work/transcription.json`;
  completa `songs.language`. Limpieza: orden de la letra preservado, palabras con guion
  unidas, alucinaciones conocidas aisladas descartadas (capa A). CLI
  `run-stage transcribe`. ~20–25 s por canción, ~5.2 GB de VRAM. El filtro
  `--hallucination_silence_threshold` de Whisper está desactivado: en rap descartaba
  frases reales.
- [x] **US-2.4 Segmentación en líneas.** Función pura `segment_lines` (mayúsculas de
  inicio de verso, puntuación, pausas ≥ 1 s, división de líneas > 8 s / 14 palabras,
  unión de líneas cortas); artefacto `work/lines.json`; CLI `run-stage segment`
  (sin GPU, ~0.3 s). Respaldo para canciones sin letra oficial.
- [x] **US-2.7 Letras oficiales alineadas** *(adelantada: va después de US-2.4)*.
  `songs.lyrics_text`; carga por `POST /admin/songs` (campo `lyrics`),
  `PUT /admin/songs/{id}/lyrics` y CLI (`add-song --lyrics`, `set-lyrics`).
  `align_lyrics` (difflib): texto y versos de la letra, tiempos de Whisper, palabras
  omitidas interpoladas; rechazo si coincide < 50%. La etapa `segment` la usa cuando
  hay letra. Canciones de prueba: 99% y 98% de coincidencia.
- [x] **US-2.5 F0 de referencia.** `PitchExtractor` → torchcrepe (`full`, viterbi) en un
  runner propio en subproceso; artefacto `work/pitch.json` (curva global MIDI +
  confianza). **Capa B anti-alucinaciones**: descarta rachas de ≥ 3 palabras
  transcriptas sin voz (las palabras sueltas sin voz son normales en rap). CLI
  `run-stage pitch` con resumen por verso. ~12 s por canción, ~2.8 GB de VRAM.
- [x] **US-2.6 Orquestación Celery.** `IngestionPipeline`: `separate → transcribe → pitch
  → segment → persist`, con estado del job por etapa, falla registrada con etapa y
  error, jobs terminados que no se repiten y jobs interrumpidos que se rehacen. `persist`
  arma y valida el `SongAnalysisData` (líneas + curva + `PipelineInfo` desde
  `work/manifest.json`) y lo publica como nueva versión actual; la canción queda
  `ready`. Tarea Celery real (límite 1 h); CLI `requeue`, `run-pipeline` y
  `run-stage persist`. End-to-end: ~95 s (demucs) y ~220 s (roformer) por canción.
  *Pendiente para E3:* durante un reproceso la canción deja de estar `ready`.

## E3 — API de catálogo

- [ ] **US-3.1** `GET /songs` (canciones READY, paginado, búsqueda).
- [ ] **US-3.2** `GET /songs/{id}` (líneas y palabras con timestamps).
- [ ] **US-3.3** `GET /songs/{id}/instrumental` (streaming con HTTP Range).
- [ ] **US-3.4** `GET /songs/{id}/pitch` (curva de referencia).
- [ ] **US-3.5** `GET /admin/songs/{id}/status`.

## E4 — Motor de scoring (100 % de cobertura)

- [ ] **US-4.1 Utilidades de pitch.** Hz → cents/MIDI, unvoiced, resampleo, plegado de octava.
- [ ] **US-4.2 DTW vectorizado.** Anti-diagonales en numpy, banda Sakoe-Chiba, costo + path.
  *Edge cases:* largos distintos, vacíos, match perfecto, mismatch total, todo unvoiced,
  una sola muestra.
- [ ] **US-4.3 Puntaje 0–100 por línea** con tolerancia en cents; hit/miss para rachas.
- [ ] **US-4.4 Agregado de sesión.** Precisión global, mejor racha, puntaje total.

## E5 — Sesión en tiempo real

- [ ] **US-5.1** `POST /sessions` (`song_id`, `player_name`, `latency_offset_ms`).
- [ ] **US-5.2 WebSocket** `/ws/sessions/{id}`: `line_pitch` → DTW en executor →
  `line_score`. Protocolo en `docs/ws-protocol.md`.
- [ ] **US-5.3** Persistencia de puntajes por línea y cierre con `finish`.
- [ ] **US-5.4** `GET /sessions/{id}/results`.

## E6 — Cliente web mínimo

- [ ] **US-6.1** Scaffolding Vite + React + TS y cliente de API tipado.
- [ ] **US-6.2** Catálogo con búsqueda.
- [ ] **US-6.3** Reproductor: instrumental + letras sincronizadas por palabra.
- [ ] **US-6.4** Calibración de latencia (tap al oír un pitido).
- [ ] **US-6.5** Micrófono + YIN en AudioWorklet, F0 acumulado por línea.
- [ ] **US-6.6** Envío por WebSocket y feedback visual por línea.
- [ ] **US-6.7** Pantalla de resultados.

## E7 — Modo práctica

- [ ] **US-7.1** Endpoint con curva de referencia y curva del usuario alineadas (path DTW).
- [ ] **US-7.2** Gráfico de líneas comparativo en el cliente web.

## Fuera del MVP

Auth JWT e historial por usuario · cola de votación de canciones · S3 · app React Native ·
multijugador.
