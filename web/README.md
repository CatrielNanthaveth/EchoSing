# EchoSing Web

Minimal browser client: catalog, karaoke player, latency calibration and real-time
scoring. React + TypeScript (strict) on Vite.

## Requirements

- Node.js >= 22.12
- The API running locally (see `backend/README.md`); CORS already allows
  `http://localhost:5173`.

## Setup

```bash
npm ci
cp .env.example .env   # optional: VITE_API_URL (default http://localhost:8000)
npm run dev            # http://localhost:5173
```

## Playing

1. **Calibrate** once per headphones/speakers (`/calibrar`): clap along with 8 beeps;
   the measured latency (output + input) is stored in the browser.
2. Pick a song and press **Cantar**: this creates a play session, opens the
   microphone and plays the instrumental. Use headphones, so the microphone does not
   pick up the track.
3. Each line is scored when it ends (score, verdict and streak); when the song ends
   the session is finished and its results open (`/sessions/{id}/results`).

How it works: the instrumental is decoded and played with Web Audio, and the
microphone is analyzed in an AudioWorklet (YIN, a frame every ~10.7 ms) on the same
`AudioContext` clock, so every pitch frame is placed exactly on the song timeline.
Frames are grouped by lyric line and sent over the WebSocket (`docs/ws-protocol.md`);
the server compensates the latency and scores with DTW.

## Commands

| Command              | Does                                                |
| -------------------- | --------------------------------------------------- |
| `npm run dev`        | Dev server with hot reload                          |
| `npm run build`      | Typecheck and production build (`dist/`)            |
| `npm run check`      | Typecheck, lint, formatting check and tests         |
| `npm run test:watch` | Tests in watch mode (Vitest + Testing Library)      |
| `npm run format`     | Format with Prettier (88 columns, like the backend) |
| `npm run gen:api`    | Regenerate the API types (below)                    |

The git pre-commit hook runs typecheck, lint and the formatting check when files
under `web/` change.

## API types

`src/api/schema.d.ts` is generated from the backend's OpenAPI contract, which also
includes the WebSocket messages. After changing an API schema in the backend:

```bash
npm run gen:api
```

It exports `openapi.json` with `uv` (no server or database needed) and runs
`openapi-typescript`. Both files are committed, so the client builds without the
backend; if the API changes incompatibly, the client stops compiling. Use the aliases
in `src/api/types.ts` and the client in `src/api/client.ts`.

`openapi-typescript` runs through `npx` with a pinned version instead of being a dev
dependency: it declares a TypeScript 5 peer, and forcing it onto TypeScript 6 trips an
npm 10 resolver bug.
