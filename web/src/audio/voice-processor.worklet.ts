// AudioWorklet that analyzes the microphone off the main thread. It runs in
// the AudioWorkletGlobalScope, whose globals are declared here.
import { FrameAnalyzer, VOICE_PROCESSOR } from "./frameAnalyzer";

declare const sampleRate: number;
declare const currentFrame: number;
declare abstract class AudioWorkletProcessor {
  readonly port: MessagePort;
}
declare function registerProcessor(
  name: string,
  processor: new () => AudioWorkletProcessor,
): void;

class VoiceProcessor extends AudioWorkletProcessor {
  readonly #analyzer = new FrameAnalyzer(sampleRate, (frame) => {
    this.port.postMessage(frame);
  });

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0];
    if (channel !== undefined) this.#analyzer.push(channel, currentFrame);
    return true;
  }
}

registerProcessor(VOICE_PROCESSOR, VoiceProcessor);
