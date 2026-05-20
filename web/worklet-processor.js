'use strict';

// PCM capture processor: Float32 → Int16, ~1024-sample (~64ms) buffer → WS
class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = new Int16Array(1024);
    this._len = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      const s = ch[i] < -1 ? -1 : ch[i] > 1 ? 1 : ch[i];
      this._buf[this._len++] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      if (this._len >= 1024) {
        const out = this._buf.slice();
        this.port.postMessage(out.buffer, [out.buffer]);
        this._len = 0;
      }
    }
    return true;
  }
}

registerProcessor('pcm-capture-processor', PCMCaptureProcessor);
