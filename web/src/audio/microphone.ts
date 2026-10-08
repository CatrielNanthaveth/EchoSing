import { VOICE_PROCESSOR, type VoiceFrame } from "./frameAnalyzer";
import processorUrl from "./voice-processor.worklet.ts?worker&url";

const loadedContexts = new WeakSet<BaseAudioContext>();

export type FrameListener = (frame: VoiceFrame) => void;

/**
 * Microphone analyzed in an AudioWorklet: emits a `VoiceFrame` every ~10 ms,
 * timestamped on the AudioContext clock.
 */
export class Microphone {
  readonly #stream: MediaStream;
  readonly #nodes: AudioNode[];
  readonly #listeners = new Set<FrameListener>();

  private constructor(stream: MediaStream, nodes: AudioNode[], port: MessagePort) {
    this.#stream = stream;
    this.#nodes = nodes;
    port.onmessage = (event: MessageEvent<VoiceFrame>) => {
      for (const listener of this.#listeners) listener(event.data);
    };
  }

  /**
   * Ask for the microphone and start analyzing it.
   *
   * Browser processing that distorts pitch or level (echo cancellation, noise
   * suppression, automatic gain) is turned off: use headphones.
   */
  static async open(context: AudioContext): Promise<Microphone> {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
        channelCount: 1,
      },
    });
    try {
      if (!loadedContexts.has(context)) {
        await context.audioWorklet.addModule(processorUrl);
        loadedContexts.add(context);
      }
      const source = context.createMediaStreamSource(stream);
      const analyzer = new AudioWorkletNode(context, VOICE_PROCESSOR, {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        channelCount: 1,
        channelCountMode: "explicit",
      });
      // Muted path to the output: keeps the node processing in every browser.
      const mute = context.createGain();
      mute.gain.value = 0;
      source.connect(analyzer).connect(mute).connect(context.destination);
      return new Microphone(stream, [source, analyzer, mute], analyzer.port);
    } catch (error) {
      for (const track of stream.getTracks()) track.stop();
      throw error;
    }
  }

  /** Receive every frame; returns a function that stops listening. */
  subscribe(listener: FrameListener): () => void {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  }

  close(): void {
    this.#listeners.clear();
    for (const node of this.#nodes) node.disconnect();
    for (const track of this.#stream.getTracks()) track.stop();
  }
}

/** A readable message for errors from getUserMedia. */
export function microphoneErrorMessage(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") {
      return "Permiso de micrófono denegado. Habilitalo en la barra de direcciones.";
    }
    if (error.name === "NotFoundError") return "No se encontró ningún micrófono.";
    if (error.name === "NotReadableError") {
      return "El micrófono está siendo usado por otra aplicación.";
    }
  }
  return error instanceof Error ? error.message : String(error);
}
