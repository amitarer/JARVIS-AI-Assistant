/* Local WebGL2 renderer. No network, Python object exposure or desktop commands. */
"use strict";
(() => {
  const canvas = document.getElementById("neural");
  let gl, programs = [], buffers = [], vaos = [], disposed = false;
  let state = "idle", running = false, raf = 0, previous = 0, clock = 0;
  let audio = 0, audioTarget = 0, lastAudioAt = 0, activity = 0, reveal = 0;
  let yaw = -0.88, pitch = 0.28, zoom = 1, rotation = true, reducedMotion = false;
  let particleCount = 0, edgeCount = 0, impulseCount = 0, quality = 1;
  let organic = 0, edgeDivisions = 1, edgeVertexCount = 0, signalClock = 0, errorTint = 0;
  let maxDpr = 1.5, targetFps = 60, dirtySize = true, lastDraw = 0;
  let selected = -1, graphData = null, selectionBuffers = [], panX = 0, panY = 0;
  let windowStart = 0, frameCount = 0, cpuSum = 0, gpuSum = 0, gpuSamples = 0;
  let slowWindows = 0, fastWindows = 0, gpuExtension = null, queries = [];
  const stats = { ready: false, error: null, frames: 0, fps: 0, cpuSubmitMs: 0,
    gpuMs: null, graphBytes: 0, quality: 1, pixelRatio: 1, contextLost: false };
  const common = `
    precision highp float;
    uniform float uTime, uAudio, uActivity, uReveal, uYaw, uPitch, uAspect, uDpr, uZoom;
    uniform float uError, uSpeaking, uFocusEnabled, uPanX, uPanY, uOrganic, uSignalTime;
    float wave(float delay) {
      float d = fract(uSignalTime - delay * 0.31);
      return exp(-pow((d - 0.16) * 22.0, 2.0));
    }
    vec3 deform(vec3 p) {
      float breathe = 1.0 + 0.005 * sin(uTime * 1.35) + uAudio * 0.026;
      p *= breathe;
      p += normalize(p + vec3(0.001)) * 0.004 * sin(p.z * 5.0 + p.y * 6.0 + uTime * 0.7);
      p += uOrganic * vec3(0.052 * sin(p.y * 2.7 + uTime * 0.65),
                           0.065 * sin(p.z * 3.4 - uTime * 0.55),
                           0.050 * sin(p.x * 3.2 + uTime * 0.45));
      float cy = cos(uYaw), sy = sin(uYaw), cp = cos(uPitch), sp = sin(uPitch);
      p.xz = mat2(cy, -sy, sy, cy) * p.xz;
      p.yz = mat2(cp, -sp, sp, cp) * p.yz;
      return p;
    }
    vec4 project(vec3 p) {
      p = deform(p);
      p.z -= 5.0;
      float f = mix(4.0, 3.3, uOrganic) * uZoom;
      return vec4(p.x * f / uAspect + uPanX * -p.z, p.y * f + uPanY * -p.z, -1.004 * p.z - 0.2004, -p.z);
    }
    vec3 tint(float heat, float depth) {
      vec3 cold = mix(vec3(0.06, 0.28, 0.76), vec3(0.17, 0.78, 1.0), depth);
      cold = mix(cold, vec3(0.73, 0.95, 1.0), clamp(heat, 0.0, 0.84));
      vec3 amber = mix(vec3(0.79, 0.45, 0.14), vec3(1.0, 0.81, 0.47), depth);
      amber = mix(amber, vec3(1.0, 0.93, 0.76), clamp(heat, 0.0, 0.86));
      cold = mix(cold, amber, uOrganic);
      return mix(cold, vec3(1.0, 0.28, 0.16), uError * 0.78);
    }
  `;
  const nodeVertex = `#version 300 es
    ${common}
    layout(location=0) in vec3 aPosition;
    layout(location=1) in float aDelay;
    layout(location=2) in float aFocus;
    out vec3 vColor;
    out float vAlpha;
    void main() {
      gl_Position = project(aPosition);
      float depth = clamp((deform(aPosition).z + 1.5) / 3.0, 0.0, 1.0);
      float signal = wave(aDelay) * (0.18 + uActivity * 0.7);
      float flicker = 0.84 + 0.16 * sin(uTime * 1.1 + aDelay * 9.0);
      float activation = smoothstep(aDelay * 0.12, aDelay * 0.12 + 0.38, uReveal);
      float heat = signal + uAudio * 0.8;
      gl_PointSize = (3.8 - uOrganic * 1.3 + depth * 2.2 + heat * 3.8 + aFocus * 4.0) * uDpr * sqrt(uZoom);
      vColor = tint(heat, depth);
      vAlpha = (0.25 + depth * 0.5 + heat * 0.30) * flicker * activation;
      vAlpha *= mix(1.0, aFocus > 0.0 ? 1.4 : 0.25, uFocusEnabled);
      if (aFocus > 1.5) vColor = vec3(0.95, 1.0, 1.0);
    }
  `;
  const nodeFragment = `#version 300 es
    precision highp float;
    in vec3 vColor;
    in float vAlpha;
    out vec4 color;
    void main() {
      float r = length(gl_PointCoord - 0.5) * 2.0;
      if (r > 1.0) discard;
      float core = exp(-r * r * 26.0);
      float halo = exp(-r * r * 5.5) * 0.25;
      color = vec4(vColor, (core + halo) * vAlpha);
    }
  `;
  const edgeVertex = `#version 300 es
    ${common}
    layout(location=0) in vec3 aPosition;
    layout(location=1) in float aDelay;
    layout(location=2) in float aFocus;
    out vec3 vColor;
    out float vAlpha;
    void main() {
      gl_Position = project(aPosition);
      float depth = clamp((deform(aPosition).z + 1.5) / 3.0, 0.0, 1.0);
      float signal = wave(aDelay);
      vColor = tint(signal * uActivity * 0.5 + uAudio * 0.4, depth);
      float activation = smoothstep(aDelay * 0.12, aDelay * 0.12 + 0.38, uReveal);
      vAlpha = (0.032 + depth * 0.085 + signal * uActivity * 0.10 + uAudio * 0.05) * activation;
      vAlpha *= 1.0 + uOrganic * 0.65;
      vAlpha *= mix(1.0, aFocus > 0.0 ? 5.0 : 0.18, uFocusEnabled);
    }
  `;
  const edgeFragment = `#version 300 es
    precision highp float;
    in vec3 vColor;
    in float vAlpha;
    out vec4 color;
    void main() { color = vec4(vColor, vAlpha); }
  `;
  const impulseVertex = `#version 300 es
    ${common}
    layout(location=0) in vec3 aFrom;
    layout(location=1) in vec3 aTo;
    layout(location=2) in float aDelay;
    out vec3 vColor;
    out float vAlpha;
    void main() {
      float t = fract(uSignalTime - aDelay * 0.31);
      float progress = clamp((t - 0.07) / 0.18, 0.0, 1.0);
      vec3 point = mix(aFrom, aTo, progress);
      point += uOrganic * normalize(aFrom + aTo + vec3(0.00001)) * 0.009 * sin(progress * 3.14159);
      gl_Position = project(point);
      float activation = smoothstep(aDelay * 0.12, aDelay * 0.12 + 0.38, uReveal);
      vAlpha = sin(progress * 3.14159) * (0.28 + uActivity * 0.7 + uAudio * 0.35) * activation;
      vColor = tint(0.88, 1.0);
      gl_PointSize = (6.0 + uActivity * 3.0 + uAudio * 3.0) * uDpr * uZoom;
    }
  `;
  const filamentVertex = `#version 300 es
    ${common}
    layout(location=0) in vec3 aPosition;
    layout(location=1) in float aDelay;
    layout(location=2) in float aFocus;
    out vec3 vColor;
    out float vAlpha;
    void main() {
      gl_Position = project(aPosition);
      float depth = clamp((deform(aPosition).z + 1.5) / 3.0, 0.0, 1.0);
      float heat = wave(aDelay) * (0.15 + uActivity * 0.55) + uAudio * 0.65;
      float activation = smoothstep(aDelay * 0.12, aDelay * 0.12 + 0.38, uReveal);
      gl_PointSize = (1.2 + depth * 0.8 + heat * 0.5) * uDpr * sqrt(uZoom);
      vColor = tint(heat + 0.18, depth);
      vAlpha = (0.34 + depth * 0.48 + heat * 0.25) * activation;
      vAlpha *= mix(1.0, aFocus > 0.0 ? 1.3 : 0.18, uFocusEnabled);
    }
  `;
  const filamentFragment = `#version 300 es
    precision highp float;
    in vec3 vColor;
    in float vAlpha;
    out vec4 color;
    void main() {
      float r = length(gl_PointCoord - 0.5) * 2.0;
      if (r > 1.0) discard;
      color = vec4(vColor, (1.0 - smoothstep(0.12, 1.0, r)) * vAlpha);
    }
  `;

  function fail(message) {
    stats.error = String(message);
    running = false;
    cancelAnimationFrame(raf);
    const failure = document.getElementById("failure");
    failure.hidden = false;
    failure.textContent = "Renderer 3D non disponibile. " + stats.error;
  }

  function program(vertex, fragment) {
    const shaders = [];
    try {
      for (const [source, type] of [[vertex, gl.VERTEX_SHADER], [fragment, gl.FRAGMENT_SHADER]]) {
        const shader = gl.createShader(type);
        shaders.push(shader);
        gl.shaderSource(shader, source);
        gl.compileShader(shader);
        if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader));
      }
      const result = gl.createProgram();
      shaders.forEach(shader => gl.attachShader(result, shader));
      gl.linkProgram(result);
      if (!gl.getProgramParameter(result, gl.LINK_STATUS)) {
        const error = gl.getProgramInfoLog(result);
        gl.deleteProgram(result);
        throw new Error(error);
      }
      const uniforms = {};
      for (const name of ["Time", "Audio", "Activity", "Reveal", "Yaw", "Pitch", "Aspect", "Dpr", "Zoom", "Error", "Speaking", "FocusEnabled", "PanX", "PanY", "Organic", "SignalTime"]) {
        uniforms[name] = gl.getUniformLocation(result, "u" + name);
      }
      programs.push({ handle: result, uniforms });
      return programs[programs.length - 1];
    } finally { shaders.forEach(shader => gl.deleteShader(shader)); }
  }

  function upload(attributes) {
    const vao = gl.createVertexArray();
    vaos.push(vao);
    gl.bindVertexArray(vao);
    attributes.forEach(([location, size, values]) => {
      const buffer = gl.createBuffer();
      buffers.push(buffer);
      if (location === 2 && size === 1 && vaos.length <= 2) selectionBuffers.push(buffer);
      const data = new Float32Array(values);
      stats.graphBytes += data.byteLength;
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, size, gl.FLOAT, false, 0, 0);
    });
    gl.bindVertexArray(null);
    return vao;
  }

  function initialize(graph, options = {}) {
    if (disposed || stats.ready || gl) return false;
    try {
      maxDpr = Math.max(0.5, Math.min(2, options.pixelRatio || 1.5));
      graphData = graph;
      organic = graph.style === "organic" ? 1 : 0;
      edgeDivisions = organic ? 3 : 1;
      targetFps = Math.max(24, Math.min(60, options.fps || 60));
      gl = canvas.getContext("webgl2", { alpha: true, antialias: false,
        premultipliedAlpha: true, powerPreference: "low-power", preserveDrawingBuffer: false });
      if (!gl) throw new Error("WebGL 2 non supportato da questa configurazione Qt/GPU.");
      gpuExtension = gl.getExtension("EXT_disjoint_timer_query_webgl2");
      program(edgeVertex, edgeFragment);
      program(nodeVertex, nodeFragment);
      program(impulseVertex, nodeFragment);
      program(filamentVertex, filamentFragment);
      const points = graph.positions.flat();
      const edgePositions = [], edgeDelays = [], starts = [], ends = [], delays = [];
      graph.edges.forEach(([a, b], index) => {
        const from = graph.positions[a], to = graph.positions[b];
        const normal = from.map((v, i) => v + to[i]);
        const length = Math.hypot(...normal) || 1;
        for (let segment = 0; segment < edgeDivisions; segment++) {
          for (const t of [segment / edgeDivisions, (segment + 1) / edgeDivisions]) {
            const arch = organic * 0.009 * Math.sin(t * Math.PI);
            edgePositions.push(...from.map((v, i) => v * (1 - t) + to[i] * t + normal[i] / length * arch));
            edgeDelays.push(graph.arrivals[a] * (1 - t) + graph.arrivals[b] * t);
          }
        }
        if (index % 4 === 0) {
          if (graph.arrivals[a] > graph.arrivals[b]) [a, b] = [b, a];
          starts.push(...graph.positions[a]);
          ends.push(...graph.positions[b]);
          delays.push(graph.arrivals[a]);
        }
      });
      upload([[0, 3, edgePositions], [1, 1, edgeDelays], [2, 1, new Float32Array(edgeDelays.length)]]);
      upload([[0, 3, points], [1, 1, graph.arrivals], [2, 1, new Float32Array(graph.positions.length)]]);
      upload([[0, 3, starts], [1, 3, ends], [2, 1, delays]]);
      particleCount = graph.positions.length;
      edgeCount = graph.edges.length;
      edgeVertexCount = edgeDelays.length;
      impulseCount = delays.length;
      gl.enable(gl.BLEND);
      gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.disable(gl.DEPTH_TEST);
      const info = gl.getExtension("WEBGL_debug_renderer_info");
      stats.renderer = info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
      stats.version = gl.getParameter(gl.VERSION);
      stats.alpha = gl.getContextAttributes().alpha;
      stats.ready = true;
      return true;
    } catch (error) { fail(error.message); return false; }
  }

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, maxDpr) * quality;
    const width = Math.max(1, Math.round(canvas.clientWidth * dpr));
    const height = Math.max(1, Math.round(canvas.clientHeight * dpr));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
      gl.viewport(0, 0, width, height);
    }
    stats.pixelRatio = dpr;
    dirtySize = false;
  }

  function render(now) {
    raf = 0;
    if (!running || disposed || !stats.ready || stats.contextLost) return;
    raf = requestAnimationFrame(render);
    if (now - lastDraw < 1000 / targetFps - 1.5) return;
    const cpuStart = performance.now();
    const delta = previous ? Math.min(0.1, (now - previous) / 1000) : 0;
    previous = lastDraw = now;
    if (!reducedMotion) clock += delta;
    reveal = Math.min(2, reveal + delta * 1.3);
    // Audio is supplied externally; it decays after missing updates. No fake voice envelope.
    if (now - lastAudioAt > 160) audioTarget *= Math.exp(-delta * 12);
    audio += (audioTarget - audio) * (1 - Math.exp(-delta * 18));
    const targetActivity = { activating: 0.25, listening: 0.17, thinking: 1,
      speaking: 0.13, confirmation: 0.12, error: 0.22 }[state] || 0;
    activity += (targetActivity - activity) * (1 - Math.exp(-delta * 4));
    if (!reducedMotion) signalClock += delta * (0.21 + activity * 0.25);
    errorTint += ((state === "error" ? 1 : 0) - errorTint) * (1 - Math.exp(-delta * 5));
    if (rotation && !reducedMotion) yaw += delta * 0.065;
    if (dirtySize || stats.deviceDpr !== window.devicePixelRatio) resize();
    stats.deviceDpr = window.devicePixelRatio;
    // Nonblocking GPU timings; no gl.finish / readPixels in the render loop.
    if (gpuExtension) {
      const disjoint = gl.getParameter(gpuExtension.GPU_DISJOINT_EXT);
      while (queries.length && gl.getQueryParameter(queries[0], gl.QUERY_RESULT_AVAILABLE)) {
        const query = queries.shift();
        if (!disjoint) { gpuSum += gl.getQueryParameter(query, gl.QUERY_RESULT) / 1e6; gpuSamples++; }
        gl.deleteQuery(query);
      }
    }
    let query = null;
    if (gpuExtension && queries.length < 4 && stats.frames % 12 === 0) {
      query = gl.createQuery();
      gl.beginQuery(gpuExtension.TIME_ELAPSED_EXT, query);
    }
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    // The fine filament speckles reuse existing GPU positions; they are not new neurons.
    for (const index of [0, 3, 1, 2]) {
      if (index === 3 && !organic) continue;
      const { handle, uniforms: u } = programs[index];
      gl.useProgram(handle);
      const values = { Time: clock, Audio: audio, Activity: activity, Reveal: reveal,
        Yaw: yaw, Pitch: pitch, Aspect: canvas.width / canvas.height, Dpr: stats.pixelRatio,
        Zoom: zoom, Error: errorTint, Speaking: state === "speaking" ? 1 : 0,
        FocusEnabled: selected >= 0 ? 1 : 0, PanX: panX, PanY: panY, Organic: organic, SignalTime: signalClock };
      for (const key in values) gl.uniform1f(u[key], values[key]);
      gl.bindVertexArray(vaos[index === 3 ? 0 : index]);
      const counts = [edgeVertexCount, particleCount, Math.floor(impulseCount * quality), Math.floor(edgeVertexCount * quality)];
      gl.drawArrays(index === 0 ? gl.LINES : gl.POINTS, 0, counts[index]);
    }
    gl.bindVertexArray(null);
    if (query) { gl.endQuery(gpuExtension.TIME_ELAPSED_EXT); queries.push(query); }
    cpuSum += performance.now() - cpuStart;
    frameCount++;
    stats.frames++;
    if (!windowStart) windowStart = now;
    if (now - windowStart > 1600) {
      stats.fps = frameCount * 1000 / (now - windowStart);
      stats.cpuSubmitMs = cpuSum / frameCount;
      stats.gpuMs = gpuSamples ? gpuSum / gpuSamples : null;
      slowWindows = stats.fps < targetFps * 0.78 ? slowWindows + 1 : 0;
      fastWindows = stats.fps > targetFps * 0.95 ? fastWindows + 1 : 0;
      if (slowWindows >= 2 && quality > 0.55) {
        quality = Math.max(0.55, quality - 0.15);
        dirtySize = true;
        slowWindows = fastWindows = 0;
      } else if (fastWindows >= 8 && quality < 1) {
        quality = Math.min(1, quality + 0.1);
        dirtySize = true;
        fastWindows = 0;
      }
      stats.quality = quality;
      windowStart = now;
      frameCount = cpuSum = gpuSum = gpuSamples = 0;
    }
  }

  function setVisible(visible) {
    const active = Boolean(visible) && !["idle", "executing"].includes(state);
    if (active && !running && stats.ready && !disposed && !stats.contextLost) {
      running = true;
      previous = lastDraw = windowStart = frameCount = cpuSum = gpuSum = gpuSamples = 0;
      raf = requestAnimationFrame(render);
    } else if (!active) {
      running = false;
      cancelAnimationFrame(raf);
      raf = 0;
      audio = audioTarget = 0;
    }
  }

  function setState(next) {
    if (!["idle", "activating", "listening", "thinking", "speaking", "executing", "confirmation", "error"].includes(next)) return false;
    const old = state;
    state = next;
    audio = audioTarget = 0;
    if (next === "activating" || ["idle", "executing"].includes(old)) reveal = 0;
    if (["idle", "executing"].includes(next)) setVisible(false);
    return true;
  }

  function setAudioLevel(level) {
    if (!Number.isFinite(level)) return false;
    audioTarget = ["listening", "speaking"].includes(state) ? Math.max(0, Math.min(1, level)) : 0;
    lastAudioAt = performance.now();
    return true;
  }

  function snapshot() {
    return { ...stats, state, running, audio, audioTarget, yaw, pitch, rotation,
      neurons: particleCount, connections: edgeCount, impulses: impulseCount, selected, zoom, panX, panY,
      style: organic ? "organic" : "cortex", filaments: graphData?.filamentCount || 0, edgeVertexCount,
      canvas: [canvas.width, canvas.height], reducedMotion };
  }

  function dispose() {
    setVisible(false);
    disposed = true;
    if (!gl) return;
    queries.forEach(query => gl.deleteQuery(query));
    buffers.forEach(buffer => gl.deleteBuffer(buffer));
    vaos.forEach(vao => gl.deleteVertexArray(vao));
    programs.forEach(p => gl.deleteProgram(p.handle));
    queries = []; buffers = []; vaos = []; programs = [];
    stats.ready = false;
    stats.graphBytes = 0;
    gl.getExtension("WEBGL_lose_context")?.loseContext();
  }

  canvas.addEventListener("webglcontextlost", event => {
    event.preventDefault();
    if (disposed) return;
    stats.contextLost = true;
    fail("Contesto GPU perso. Chiudi e riapri l’anteprima.");
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) setVisible(false);
  });
  new ResizeObserver(() => { dirtySize = true; }).observe(canvas);
  function selectNeuron(index) {
    if (!graphData || !Number.isInteger(index) || index < -1 || index >= particleCount) return false;
    selected = index;
    const nodeFocus = new Float32Array(particleCount);
    const edgeFocus = new Float32Array(edgeVertexCount);
    if (index >= 0) {
      nodeFocus[index] = 2;
      graphData.edges.forEach(([a, b], i) => {
        if (a === index || b === index) {
          nodeFocus[a === index ? b : a] = 1;
          edgeFocus.fill(1, i * edgeDivisions * 2, (i + 1) * edgeDivisions * 2);
        }
      });
    }
    for (const [i, values] of [[0, edgeFocus], [1, nodeFocus]]) {
      gl.bindBuffer(gl.ARRAY_BUFFER, selectionBuffers[i]);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, values);
    }
    return true;
  }

  // Same deformation/projection as the vertex shader, in CSS pixels for picking.
  function screenPosition(index) {
    if (!graphData || !graphData.positions[index]) return null;
    let [x, y, z] = graphData.positions[index];
    const breathe = 1 + 0.005 * Math.sin(clock * 1.35) + audio * 0.026;
    x *= breathe; y *= breathe; z *= breathe;
    const length = Math.hypot(x + 0.001, y + 0.001, z + 0.001);
    const displacement = 0.004 * Math.sin(z * 5 + y * 6 + clock * 0.7);
    x += (x + 0.001) / length * displacement;
    y += (y + 0.001) / length * displacement;
    z += (z + 0.001) / length * displacement;
    const px = x, py = y, pz = z;
    x += organic * 0.052 * Math.sin(py * 2.7 + clock * 0.65);
    y += organic * 0.065 * Math.sin(pz * 3.4 - clock * 0.55);
    z += organic * 0.050 * Math.sin(px * 3.2 + clock * 0.45);
    const xr = Math.cos(yaw) * x + Math.sin(yaw) * z;
    const zr = -Math.sin(yaw) * x + Math.cos(yaw) * z;
    const yr = Math.cos(pitch) * y + Math.sin(pitch) * zr;
    const depth = -Math.sin(pitch) * y + Math.cos(pitch) * zr;
    const focal = organic ? 3.3 : 4.0;
    const ndcX = xr * focal * zoom / (canvas.clientWidth / canvas.clientHeight) / (5 - depth) + panX;
    const ndcY = yr * focal * zoom / (5 - depth) + panY;
    return { x: (ndcX + 1) * canvas.clientWidth / 2,
      y: (1 - ndcY) * canvas.clientHeight / 2, depth };
  }

  function pick(x, y) {
    if (!running || !graphData) return;
    let best = -1, bestScore = Infinity;
    for (let i = 0; i < particleCount; i++) {
      const p = screenPosition(i);
      const d = Math.hypot(x - p.x, y - p.y);
      const score = d + (1.5 - p.depth) * 1.8;
      if (d < 11 && score < bestScore) { best = i; bestScore = score; }
    }
    selectNeuron(best);
  }

  let dragging = false, lastX = 0, lastY = 0, downX = 0, downY = 0, panning = false;
  canvas.addEventListener("pointerdown", event => {
    dragging = true; lastX = downX = event.clientX; lastY = downY = event.clientY;
    panning = event.shiftKey || event.button === 1;
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointerup", event => {
    if (Math.hypot(event.clientX - downX, event.clientY - downY) < 5 && !panning) {
      const rect = canvas.getBoundingClientRect();
      pick(event.clientX - rect.left, event.clientY - rect.top);
    }
    dragging = false;
  });
  canvas.addEventListener("pointercancel", () => { dragging = false; });
  canvas.addEventListener("pointermove", event => {
    if (!dragging) return;
    if (panning) {
      panX += (event.clientX - lastX) * 2 / canvas.clientWidth;
      panY -= (event.clientY - lastY) * 2 / canvas.clientHeight;
    } else {
      yaw += (event.clientX - lastX) * 0.006;
      pitch = Math.max(-1.2, Math.min(1.2, pitch + (event.clientY - lastY) * 0.006));
    }
    lastX = event.clientX; lastY = event.clientY;
  });
  canvas.addEventListener("wheel", event => {
    event.preventDefault();
    zoom = Math.max(0.5, Math.min(6, zoom * Math.exp(-event.deltaY * 0.001)));
  }, { passive: false });
  function focusNeuron() {
    if (selected < 0) return;
    zoom = Math.max(2.5, zoom);
    const p = screenPosition(selected);
    panX -= p.x * 2 / canvas.clientWidth - 1;
    panY += p.y * 2 / canvas.clientHeight - 1;
    rotation = false;
  }
  window.neural = Object.freeze({ initialize, setState, setAudioLevel, setVisible, snapshot, dispose, selectNeuron, screenPosition, focusNeuron,
    setRotation(value) { rotation = Boolean(value); },
    setReducedMotion(value) { reducedMotion = Boolean(value); },
    setZoom(value) { if (Number.isFinite(value)) zoom = Math.max(0.5, Math.min(6, value)); },
    resetView() { yaw = -0.88; pitch = 0.28; zoom = 1; panX = panY = 0; selectNeuron(-1); }
  });
})();
