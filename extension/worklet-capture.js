// Accumulates audio into fixed-size blocks and posts interleaved stereo
// Float32Array chunks back to the main (offscreen document) thread.
class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.blockSize = options.processorOptions.blockSize;
    this.left = new Float32Array(this.blockSize);
    this.right = new Float32Array(this.blockSize);
    this.writeIndex = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    const chL = input[0];
    const chR = input.length > 1 ? input[1] : input[0];
    const frames = chL.length;

    for (let i = 0; i < frames; i++) {
      this.left[this.writeIndex] = chL[i];
      this.right[this.writeIndex] = chR[i];
      this.writeIndex++;

      if (this.writeIndex === this.blockSize) {
        const interleaved = new Float32Array(this.blockSize * 2);
        for (let j = 0; j < this.blockSize; j++) {
          interleaved[j * 2] = this.left[j];
          interleaved[j * 2 + 1] = this.right[j];
        }
        this.port.postMessage(interleaved, [interleaved.buffer]);
        this.writeIndex = 0;
      }
    }
    return true;
  }
}

registerProcessor("capture-processor", CaptureProcessor);
