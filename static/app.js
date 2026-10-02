'use strict';

/* ================= 全局状态 ================= */
const PALETTE = ['#2f9e44', '#1971c2', '#e8590c', '#9c36b5', '#c2255c', '#0c8599', '#5f3dc4', '#b0891c'];
let nextId = 1;
const uid = () => 'id' + (nextId++);

const state = {
  mode: 'single',                 // 'single' | 'blend'
  room: { width: 6.5, depth: 8.0, height: 2.8, margin: 0.3 },
  screen: { width: 2.2, height: 1.24, bottom: 0.9, cx: 3.25 },
  schemes: [],
  obstacles: [],
  selectedSchemeId: null,
  selectedObstacleId: null,
  point: { x: 3.25, y: 3.6 },     // 单机：镜头安装点（顶视图坐标）
  lensHeight: 1.55,               // 单机：镜头高度
  showAll: true,
  drawMode: false,
  blendTemplate: null,            // 示例携带的拼接配置（切换到拼接模式时取用）
  blend: {
    segments: [],                 // [{id, scheme:{镜头参数}, u0,u1, min_overlap, clearance, point:{x,y}, lensZ, cal:{base,attMin,attMax}}]
    selectedIdx: 0,
  },
  cal: { target: 150, tolerance: 10 },   // 融合校准：整幅幕布目标亮度与容差
  calBands: {},                   // 重叠带采样：{"0": [{u,left,right},…]}，键为左侧设备序号
};

const DEFAULT_SEG_CAL = { base: 160, attMin: 0.4, attMax: 1.0 };

let result = null;                // 最近一次单机计算结果
let resultById = {};
let blendResult = null;           // 最近一次拼接联合计算结果
let calResult = null;             // 最近一次画面融合校准结果
let drag = null;                  // 当前拖拽会话
let examples = [];

/* ================= 工具 ================= */
const SVGNS = 'http://www.w3.org/2000/svg';
const topSvg = document.getElementById('topView');
const sideSvg = document.getElementById('sideView');
const stripSvg = document.getElementById('stripView');

function el(name, attrs = {}, parent = null) {
  const e = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const fmt = (v, d = 2) => Number(v).toFixed(d);
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function svgWorld(svg, e) {
  const pt = new DOMPoint(e.clientX, e.clientY);
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}
function colorOf(id) {
  const i = state.schemes.findIndex(s => s.id === id);
  return PALETTE[(i < 0 ? 0 : i) % PALETTE.length];
}
function devColor(k) { return PALETTE[k % PALETTE.length]; }
function currentScheme() {
  return state.schemes.find(s => s.id === state.selectedSchemeId) || null;
}
function blendSegs() { return state.blend.segments; }
function currentSeg() { return blendSegs()[state.blend.selectedIdx] || null; }
function screenLeftX() { return state.screen.cx - state.screen.width / 2; }
function uToX(u) { return screenLeftX() + u; }
function xToU(x) { return x - screenLeftX(); }
function segCenterX(seg) { return uToX((seg.u0 + seg.u1) / 2); }

/* ================= 数据清洗 ================= */
function sanitizeSingleParams(sch) {
  sch.tr_min = clamp(sch.tr_min, 0.1, 10);
  sch.tr_max = clamp(sch.tr_max, 0.1, 10);
  if (sch.tr_min > sch.tr_max) [sch.tr_min, sch.tr_max] = [sch.tr_max, sch.tr_min];
  sch.h_shift = clamp(sch.h_shift, 0, 1.5);
  sch.v_shift = clamp(sch.v_shift, 0, 1.5);
  sch.body_w = clamp(sch.body_w, 0.1, 2.5);
  sch.body_d = clamp(sch.body_d, 0.1, 2.5);
  sch.body_h = clamp(sch.body_h, 0.05, 1.5);
}

function sanitize() {
  const r = state.room, s = state.screen;
  r.width = clamp(r.width, 1, 30);
  r.depth = clamp(r.depth, 1, 40);
  r.height = clamp(r.height, 1.8, 10);
  r.margin = clamp(r.margin, 0, Math.min(r.width, r.depth) / 2 - 0.01);
  s.width = clamp(s.width, 0.5, r.width);
  s.height = clamp(s.height, 0.4, r.height);
  s.bottom = clamp(s.bottom, 0, r.height - s.height);
  s.cx = clamp(s.cx, s.width / 2, r.width - s.width / 2);
  for (const sch of state.schemes) sanitizeSingleParams(sch);
  for (const ob of state.obstacles) {
    ob.w = clamp(ob.w, 0.1, r.width);
    ob.h = clamp(ob.h, 0.1, r.depth);
    ob.x = clamp(ob.x, 0, r.width - ob.w);
    ob.y = clamp(ob.y, 0, r.depth - ob.h);
  }
  if (state.mode === 'single') {
    state.point.x = clamp(state.point.x, 0, r.width);
    state.point.y = clamp(state.point.y, 0, r.depth);
    state.lensHeight = clamp(state.lensHeight, 0, r.height);
    const sel = resultById[state.selectedSchemeId];
    if (sel && sel.ranges.z) {
      state.lensHeight = clamp(state.lensHeight, sel.ranges.z[0], sel.ranges.z[1]);
    }
  } else {
    const sc = s.bottom + s.height / 2;
    state.cal.target = clamp(state.cal.target, 1, 100000);
    state.cal.tolerance = clamp(state.cal.tolerance, 0, state.cal.target - 0.01);
    for (const seg of blendSegs()) {
      sanitizeSingleParams(seg.scheme);
      seg.u0 = clamp(seg.u0, -s.width * 0.5, s.width * 1.5);
      seg.u1 = clamp(seg.u1, -s.width * 0.5, s.width * 1.5);
      seg.min_overlap = clamp(seg.min_overlap, 0, s.width);
      seg.clearance = clamp(seg.clearance, 0, 2);
      seg.lensZ = clamp(seg.lensZ ?? sc, 0, r.height);
      // 校准测量：基准亮度与可调衰减上下限
      seg.cal = seg.cal || { ...DEFAULT_SEG_CAL };
      seg.cal.base = clamp(seg.cal.base, 0.01, 100000);
      seg.cal.attMin = clamp(seg.cal.attMin, 0, 1);
      seg.cal.attMax = clamp(seg.cal.attMax, seg.cal.attMin, 1);
      if (seg.point) {
        seg.point.x = clamp(seg.point.x, 0, r.width);
        seg.point.y = clamp(seg.point.y, 0, r.depth);
      }
      // 按该台垂直可行域夹取镜头高度（依据最近一次拼接结果）
      const dv = blendDeviceResult(blendSegs().indexOf(seg));
      if (dv && dv.ranges && dv.ranges.z) {
        seg.lensZ = clamp(seg.lensZ, dv.ranges.z[0], dv.ranges.z[1]);
      }
    }
    // 重叠带采样：u 夹到当前带内、亮度非负
    const segs = blendSegs();
    for (const [key, samples] of Object.entries(state.calBands)) {
      const k = Number(key);
      if (!(k >= 0 && k < segs.length - 1)) { delete state.calBands[key]; continue; }
      const u0 = segs[k + 1].u0, u1 = segs[k].u1;
      for (const smp of samples) {
        smp.u = clamp(smp.u, u0, u1);
        smp.left = clamp(smp.left, 0, 100000);
        smp.right = clamp(smp.right, 0, 100000);
      }
    }
  }
}

function blendDeviceResult(k) {
  if (!blendResult || blendResult.error || !blendResult.devices) return null;
  if (k < 0 || k >= blendResult.count) return null;
  return blendResult.devices[k];
}

/* ================= 服务器计算 ================= */
let computeTimer = null, computeSeq = 0;
function scheduleCompute() {
  clearTimeout(computeTimer);
  computeTimer = setTimeout(doCompute, 40);
}

function blendPayload() {
  const segments = blendSegs().map(seg => ({
    scheme: { ...seg.scheme, u0: seg.u0, u1: seg.u1 },
    min_overlap: seg.min_overlap,
    clearance: seg.clearance,
  }));
  return {
    room: state.room, screen: state.screen, obstacles: state.obstacles,
    segments,
    points: blendSegs().map(seg => seg.point ? { ...seg.point } : null),
    lens_heights: blendSegs().map(seg => seg.lensZ),
  };
}

function calibratePayload() {
  /* 校准请求 = 拼接输入（沿用 /api/blend）+ 目标亮度 + 逐机测量 + 重叠带采样；
     仅提交当前几何上确实存在的重叠带（其余保留在界面状态中不上送） */
  const payload = blendPayload();
  const segs = blendSegs();
  payload.target = { luminance: state.cal.target, tolerance: state.cal.tolerance };
  payload.devices = segs.map(seg => ({
    base_luminance: seg.cal.base, att_min: seg.cal.attMin, att_max: seg.cal.attMax,
  }));
  payload.overlaps = [];
  for (let k = 0; k < segs.length - 1; k++) {
    if (segs[k].u1 - segs[k + 1].u0 <= 1e-9) continue;
    const samples = (state.calBands[String(k)] || [])
      .map(s => ({ u: s.u, left: s.left, right: s.right }));
    if (samples.length) payload.overlaps.push({ between: [k, k + 1], samples });
  }
  return payload;
}

async function doCompute() {
  const seq = ++computeSeq;
  try {
    if (state.mode === 'single') {
      const payload = {
        room: state.room, screen: state.screen, schemes: state.schemes,
        obstacles: state.obstacles, point: state.point, lens_height: state.lensHeight,
      };
      const res = await fetch('/api/compute', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok || seq !== computeSeq) return;
      result = await res.json();
      resultById = {};
      for (const s of result.schemes) resultById[s.id] = s;
    } else {
      const post = (url, body) => fetch(url, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const [resB, resC] = await Promise.all([
        post('/api/blend', blendPayload()),
        post('/api/calibrate', calibratePayload()),
      ]);
      if (seq !== computeSeq) return;
      if (!resB.ok) {
        if (resB.status === 400) blendResult = await resB.json().catch(() => null);
        if (resC.status === 400) calResult = await resC.json().catch(() => calResult);
        render();
        return;
      }
      blendResult = await resB.json();
      if (resC.ok || resC.status === 400) {
        calResult = await resC.json().catch(() => calResult);
      }
      // 初次求解（存在设备尚无安装点）时自动采纳服务器建议点，保持整体状态一致；
      // 用户拖动导致的 joint_conflict 保留用户当前点，由其点击「采纳建议点」
      // 或点击顶视图 × 标记，避免拖动松手后点位跳动。
      const needInit = blendSegs().some(seg => !seg.point) &&
                       blendResult.suggested_points &&
                       ['ok', 'joint_conflict'].includes(blendResult.status);
      if (needInit) {
        adoptSuggested(false);
      }
    }
    render();
  } catch (err) { /* 网络异常时保留旧结果 */ }
}

function adoptSuggested(recompute = true) {
  if (!blendResult || !blendResult.suggested_points) return;
  blendResult.suggested_points.forEach((p, k) => {
    if (blendSegs()[k]) blendSegs()[k].point = { ...p };
  });
  if (recompute) onStateChange();
  else render();
}

function onStateChange() {
  render();
  scheduleCompute();
}

/* ================= 模式切换 / 区间初始化 ================= */
function makeBlendSegment(template, idx, fallbackScheme) {
  const sc = state.screen.bottom + state.screen.height / 2;
  const calDev = state.blendTemplate && state.blendTemplate.calibrate &&
                 state.blendTemplate.calibrate.devices
    ? state.blendTemplate.calibrate.devices[idx] : null;
  const cal = calDev
    ? { base: calDev.base_luminance, attMin: calDev.att_min, attMax: calDev.att_max }
    : { ...DEFAULT_SEG_CAL };
  if (template) {
    const src = state.schemes[template.scheme_idx] || fallbackScheme;
    return {
      id: uid(),
      scheme: { name: `${idx + 1}号机 · ${src.name}`, ...sanitizeClone(src) },
      u0: template.u0, u1: template.u1,
      min_overlap: template.min_overlap ?? 0.2,
      clearance: template.clearance ?? 0.3,
      point: null, lensZ: sc, cal,
    };
  }
  return {
    id: uid(),
    scheme: { name: `${idx + 1}号机`, ...sanitizeClone(fallbackScheme) },
    u0: 0, u1: 0, min_overlap: 0.2, clearance: 0.3,
    point: null, lensZ: sc, cal,
  };
}

function sanitizeClone(src) {
  const c = { ...src };
  delete c.id;
  return c;
}

function splitSegmentsEven(n) {
  /* 均分：n 台连续覆盖整幅幕，相邻重叠 ov，两端各越界 ext；
     令 u0_0=-ext、u1_{n-1}=Sw+ext，相邻 u0_{k+1}=u1_k-ov。 */
  const Sw = state.screen.width;
  const ov = Math.min(0.2, Sw / 6), ext = 0.1;
  const w = (Sw + 2 * ext + (n - 1) * ov) / n;
  const template = state.blendTemplate;
  const old = blendSegs();
  const segs = [];
  for (let k = 0; k < n; k++) {
    const u0 = -ext + k * (w - ov);
    const u1 = u0 + w;
    let seg;
    if (old[k]) {
      seg = old[k];
    } else {
      const t = template && template.segments[k];
      const fb = state.schemes[0] || {
        name: '镜头 1.3–2.1', tr_min: 1.3, tr_max: 2.1, h_shift: 0.4, v_shift: 0.5,
        body_w: 0.42, body_d: 0.35, body_h: 0.16,
      };
      seg = makeBlendSegment(t, k, fb);
    }
    seg.u0 = u0; seg.u1 = u1;
    seg.point = null;                 // 重分区间后由服务器重新给出建议点
    segs.push(seg);
  }
  state.blend.segments = segs;
  state.blend.selectedIdx = clamp(state.blend.selectedIdx, 0, n - 1);
  // 台数变化后仅保留仍然有效的重叠带采样（键为左侧设备序号）
  for (const key of Object.keys(state.calBands)) {
    if (Number(key) >= n - 1) delete state.calBands[key];
  }
}

function enterBlendMode() {
  state.mode = 'blend';
  if (state.blendTemplate) {
    // 示例携带拼接配置：按模板重建区间
    const segs = [];
    state.blendTemplate.segments.forEach((t, k) => {
      const fb = state.schemes[t.scheme_idx] || state.schemes[0] || {
        name: '镜头 1.3–2.1', tr_min: 1.3, tr_max: 2.1, h_shift: 0.4, v_shift: 0.5,
        body_w: 0.42, body_d: 0.35, body_h: 0.16,
      };
      segs.push(makeBlendSegment(t, k, fb));
    });
    state.blend.segments = segs;
    state.blend.selectedIdx = 0;
    // 示例携带的校准测量：目标亮度/容差、各机基准与衰减范围、重叠带采样
    const tc = state.blendTemplate.calibrate;
    if (tc) {
      state.cal.target = tc.target ?? 150;
      state.cal.tolerance = tc.tolerance ?? 10;
      state.calBands = {};
      for (const ob of tc.overlaps || []) {
        state.calBands[String(ob.between[0])] =
          ob.samples.map(s => ({ u: s.u, left: s.left, right: s.right }));
      }
    } else {
      state.calBands = {};
    }
  } else if (!state.blend.segments.length) {
    splitSegmentsEven(2);
  }
  document.getElementById('blendCount').value = String(blendSegs().length);
  applyModeChrome();
  onStateChange();
}

function enterSingleMode() {
  state.mode = 'single';
  applyModeChrome();
  onStateChange();
}

function applyModeChrome() {
  const blend = state.mode === 'blend';
  document.getElementById('modeSingle').classList.toggle('active', !blend);
  document.getElementById('modeBlend').classList.toggle('active', blend);
  document.querySelectorAll('.mode-single').forEach(n => { n.hidden = blend; });
  document.querySelectorAll('.mode-blend').forEach(n => { n.hidden = !blend; });
  document.getElementById('showAllWrap').style.display = blend ? 'none' : '';
  document.getElementById('topTitle').textContent = blend
    ? '顶视图（多机拼接 · 虚线框=检修包络 · ○=当前安装点 · ×=服务器建议点 · 拖动任一点即时重算）'
    : '顶视图（单击/拖动设置安装点 · 拖动幕布与禁装区即时重算）';
  document.getElementById('sideTitle').textContent = blend
    ? '侧视图（多机拼接 · 各机镜头高度独立 · 拖动机身即时重算）'
    : '侧视图（沿幕布墙剖面 · 拖动投影机调整镜头高度与距离）';
}

/* ================= SVG 公共件 ================= */
function addDefs(svg, suffix) {
  const defs = el('defs', {}, svg);
  const mk = el('marker', {
    id: 'arrow' + suffix, viewBox: '0 0 10 10', refX: 8, refY: 5,
    markerWidth: 0.13, markerHeight: 0.13, markerUnits: 'userSpaceOnUse',
    orient: 'auto-start-reverse',
  }, defs);
  el('path', { d: 'M 0 1 L 9 5 L 0 9 z', fill: '#868e96' }, mk);
  const pat = el('pattern', {
    id: 'hatch' + suffix, width: 0.14, height: 0.14,
    patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)',
  }, defs);
  el('rect', { width: 0.14, height: 0.14, fill: 'rgba(224,49,49,0.10)' }, pat);
  el('line', { x1: 0, y1: 0, x2: 0, y2: 0.14, stroke: 'rgba(224,49,49,0.55)', 'stroke-width': 0.035 }, pat);
  // 重叠区斜纹（绿色）
  const ovPat = el('pattern', {
    id: 'ovhatch' + suffix, width: 0.12, height: 0.12,
    patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(-45)',
  }, defs);
  el('rect', { width: 0.12, height: 0.12, fill: 'rgba(47,158,68,0.10)' }, ovPat);
  el('line', { x1: 0, y1: 0, x2: 0, y2: 0.12, stroke: 'rgba(47,158,68,0.6)', 'stroke-width': 0.03 }, ovPat);
}

function textAt(svg, x, y, str, size = 0.13, fill = '#495057', anchor = 'middle') {
  const t = el('text', {
    x, y, 'font-size': size, fill, 'text-anchor': anchor,
    'dominant-baseline': 'middle', class: 'halo',
  }, svg);
  t.textContent = str;
  return t;
}

/* 线性尺寸标注 */
function drawDim(svg, x1, y1, x2, y2, off, label, suffix) {
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return;
  const nx = -dy / len, ny = dx / len;
  const ax = x1 + nx * off, ay = y1 + ny * off;
  const bx = x2 + nx * off, by = y2 + ny * off;
  const g = el('g', { class: 'dim' }, svg);
  const c = '#868e96';
  el('line', { x1, y1, x2: ax, y2: ay, stroke: c, 'stroke-width': 0.008 }, g);
  el('line', { x1: x2, y1: y2, x2: bx, y2: by, stroke: c, 'stroke-width': 0.008 }, g);
  el('line', {
    x1: ax, y1: ay, x2: bx, y2: by, stroke: c, 'stroke-width': 0.012,
    'marker-start': `url(#arrow${suffix})`, 'marker-end': `url(#arrow${suffix})`,
  }, g);
  textAt(g, (ax + bx) / 2, (ay + by) / 2 - 0.02, label, 0.13, '#495057');
}

function drawRoom(svg, W, D, m) {
  el('rect', { x: 0, y: 0, width: W, height: D, fill: '#fbfcfd', stroke: '#343a40', 'stroke-width': 0.03 }, svg);
  for (let gx = 1; gx < W; gx++) el('line', { x1: gx, y1: 0, x2: gx, y2: D, stroke: '#eef1f3', 'stroke-width': 0.01 }, svg);
  for (let gy = 1; gy < D; gy++) el('line', { x1: 0, y1: gy, x2: W, y2: gy, stroke: '#eef1f3', 'stroke-width': 0.01 }, svg);
  if (m > 0.001) {
    el('rect', {
      x: m, y: m, width: W - 2 * m, height: D - 2 * m, fill: 'none',
      stroke: '#adb5bd', 'stroke-width': 0.012, 'stroke-dasharray': '0.09 0.05',
    }, svg);
    textAt(svg, W - m - 0.06, m + 0.12, `墙面余量 ${fmt(m)}m`, 0.11, '#868e96', 'end');
  }
}

function drawObstacles(svg) {
  for (const ob of state.obstacles) {
    const isSel = ob.id === state.selectedObstacleId;
    const g = el('g', {}, svg);
    el('rect', {
      x: ob.x, y: ob.y, width: ob.w, height: ob.h,
      fill: 'url(#hatchT)', stroke: '#e03131',
      'stroke-width': isSel ? 0.03 : 0.018, class: 'ob-rect',
    }, g).addEventListener('pointerdown', e => {
      state.selectedObstacleId = ob.id;
      const w = svgWorld(svg, e);
      startDrag(e, { type: 'ob', id: ob.id, dx: w.x - ob.x, dy: w.y - ob.y });
      onStateChange();
    });
    textAt(g, ob.x + ob.w / 2, ob.y + ob.h / 2 - 0.08, ob.name, 0.12, '#c92a2a');
    textAt(g, ob.x + ob.w / 2, ob.y + ob.h / 2 + 0.08, `${fmt(ob.w)}×${fmt(ob.h)}m`, 0.1, '#c92a2a');
    if (isSel) {
      el('circle', { cx: ob.x + ob.w, cy: ob.y + ob.h, r: 0.08, class: 'resize-handle' }, g)
        .addEventListener('pointerdown', e => startDrag(e, { type: 'obresize', id: ob.id }));
    }
  }
  if (drag && drag.type === 'draw') {
    const x = Math.min(drag.x0, drag.x1), y = Math.min(drag.y0, drag.y1);
    const w = Math.abs(drag.x1 - drag.x0), h = Math.abs(drag.y1 - drag.y0);
    el('rect', {
      x, y, width: w, height: h, fill: 'rgba(224,49,49,0.15)',
      stroke: '#e03131', 'stroke-width': 0.02, 'stroke-dasharray': '0.08 0.05',
    }, svg);
    textAt(svg, x + w / 2, y + h / 2, `${fmt(w)}×${fmt(h)}m`, 0.12, '#c92a2a');
  }
}

function drawScreenCore(svg, s) {
  el('rect', { x: s.cx - s.width / 2, y: -0.07, width: s.width, height: 0.07, fill: '#1864ab' }, svg)
    .addEventListener('pointerdown', e => {
      const w = svgWorld(svg, e);
      startDrag(e, { type: 'screen', dx: w.x - s.cx });
    });
  el('rect', {
    x: s.cx - s.width / 2, y: -0.14, width: s.width, height: 0.2,
    fill: '#1864ab', 'fill-opacity': 0.12, class: 'screen-hit',
  }, svg).addEventListener('pointerdown', e => {
    const w = svgWorld(svg, e);
    startDrag(e, { type: 'screen', dx: w.x - s.cx });
  });
  textAt(svg, s.cx, -0.28, '幕布', 0.12, '#1864ab');
}

/* ================= 顶视图（单机） ================= */
const TOP_PAD = { l: 1.15, t: 0.85, r: 1.05, b: 0.95 };

function renderTopSingle() {
  const svg = topSvg;
  const { width: W, depth: D, margin: m } = state.room;
  const s = state.screen;
  svg.setAttribute('viewBox', `${-TOP_PAD.l} ${-TOP_PAD.t} ${W + TOP_PAD.l + TOP_PAD.r} ${D + TOP_PAD.t + TOP_PAD.b}`);
  addDefs(svg, 'T');

  drawRoom(svg, W, D, m);
  el('line', { x1: s.cx, y1: 0, x2: s.cx, y2: D, stroke: '#e9ecef', 'stroke-width': 0.012, 'stroke-dasharray': '0.1 0.06' }, svg);

  if (result) {
    const ordered = [...result.schemes].sort((a, b) => (a.id === state.selectedSchemeId ? 1 : 0) - (b.id === state.selectedSchemeId ? 1 : 0));
    for (const sr of ordered) {
      const isSel = sr.id === state.selectedSchemeId;
      if (!isSel && !state.showAll) continue;
      const color = colorOf(sr.id);
      for (const r of sr.region) {
        if (r[2] - r[0] <= 1e-6 && r[3] - r[1] > 1e-6) {
          el('line', {
            x1: r[0], y1: r[1], x2: r[2], y2: r[3],
            stroke: color, 'stroke-width': isSel ? 0.07 : 0.05,
            'stroke-linecap': 'round', 'stroke-opacity': isSel ? 0.95 : 0.55,
          }, svg);
          if (isSel) {
            for (const yy of [r[1], r[3]]) {
              el('line', { x1: r[0] - 0.1, y1: yy, x2: r[0] + 0.1, y2: yy, stroke: color, 'stroke-width': 0.02, 'stroke-opacity': 0.9 }, svg);
            }
          }
        } else {
          el('rect', {
            x: r[0], y: r[1], width: Math.max(0, r[2] - r[0]), height: Math.max(0, r[3] - r[1]),
            fill: color, 'fill-opacity': isSel ? 0.30 : 0.10,
            stroke: color, 'stroke-width': isSel ? 0.02 : 0.01, 'stroke-opacity': isSel ? 0.95 : 0.45,
          }, svg);
        }
      }
    }
    const sel = resultById[state.selectedSchemeId];
    if (sel) {
      const color = colorOf(sel.id);
      if (sel.base_rect) {
        const b = sel.base_rect;
        el('rect', {
          x: b[0], y: b[1], width: b[2] - b[0], height: b[3] - b[1], fill: 'none',
          stroke: color, 'stroke-width': 0.018, 'stroke-dasharray': '0.1 0.05', 'stroke-opacity': 0.8,
        }, svg);
      }
      for (const [yy, lbl] of [[sel.derived.d_min, `最近投射 ${fmt(sel.derived.d_min)}m`],
                               [sel.derived.d_max, `最远投射 ${fmt(sel.derived.d_max)}m`]]) {
        if (yy > 0.01 && yy < D - 0.01) {
          el('line', { x1: 0, y1: yy, x2: W, y2: yy, stroke: color, 'stroke-width': 0.014, 'stroke-dasharray': '0.14 0.07', 'stroke-opacity': 0.7 }, svg);
          textAt(svg, 0.06, yy - 0.1, lbl, 0.11, color, 'start');
        }
      }
      if (sel.domain === 'line' && sel.line_length > 0 && sel.region.length) {
        const f = sel.region[0];
        textAt(svg, f[0] + 0.14, (f[1] + f[3]) / 2,
          `安装线可行长度 ${fmt(sel.line_length)} m`, 0.12, color, 'start');
      }
    }
  }

  const sch = currentScheme();
  const sel = resultById[state.selectedSchemeId];
  const p = state.point;
  if (sch && sel) {
    el('polygon', {
      points: `${p.x},${p.y} ${s.cx - s.width / 2},0 ${s.cx + s.width / 2},0`,
      fill: 'rgba(25,113,194,0.08)', stroke: '#1971c2',
      'stroke-width': 0.014, 'stroke-dasharray': '0.07 0.05',
    }, svg);
  }

  drawObstacles(svg);
  drawScreenCore(svg, s);

  if (sch && sel) {
    const ok = sel.point && sel.point.ok;
    el('rect', {
      x: p.x - sch.body_w / 2, y: p.y, width: sch.body_w, height: sch.body_d,
      fill: ok ? 'rgba(47,158,68,0.45)' : 'rgba(224,49,49,0.45)',
      stroke: ok ? '#2b8a3e' : '#e03131', 'stroke-width': 0.02,
    }, svg);
    const g = el('g', { class: 'point-handle' }, svg);
    el('circle', { cx: p.x, cy: p.y, r: 0.09, fill: 'rgba(25,113,194,0.25)' }, g);
    el('circle', { cx: p.x, cy: p.y, r: 0.05, fill: '#fff', stroke: '#1971c2', 'stroke-width': 0.025 }, g);
    g.addEventListener('pointerdown', e => startDrag(e, { type: 'point' }));
    textAt(svg, p.x + 0.14, p.y - 0.12, '镜头', 0.11, '#1971c2', 'start');
    drawDim(svg, 0, p.y, p.x, p.y, -0.26, `x=${fmt(p.x)}m`, 'T');
    drawDim(svg, p.x, 0, p.x, p.y, 0.26, `L=${fmt(p.y)}m`, 'T');
  }

  drawDim(svg, 0, D, W, D, 0.42, `房间宽 ${fmt(W)} m`, 'T');
  drawDim(svg, W, 0, W, D, -0.42, `进深 ${fmt(D)} m`, 'T');
  drawDim(svg, s.cx - s.width / 2, 0, s.cx + s.width / 2, 0, -0.5, `幕宽 ${fmt(s.width)} m`, 'T');
}

/* ================= 顶视图（拼接） ================= */
function renderTopBlend() {
  const svg = topSvg;
  const { width: W, depth: D, margin: m } = state.room;
  const s = state.screen;
  const segs = blendSegs();
  const n = segs.length;
  // 区间可能越界，扩展标注范围
  const minU = Math.min(0, ...segs.map(g => g.u0));
  const maxU = Math.max(s.width, ...segs.map(g => g.u1));
  const xLo = Math.min(0, uToX(minU));
  const xHi = Math.max(W, uToX(maxU));
  svg.setAttribute('viewBox', `${xLo - TOP_PAD.l} ${-TOP_PAD.t} ${xHi - xLo + TOP_PAD.l + TOP_PAD.r} ${D + TOP_PAD.t + TOP_PAD.b}`);
  addDefs(svg, 'T');

  drawRoom(svg, W, D, m);

  if (blendResult && !blendResult.error) {
    // 非选中设备先画，选中设备最后画
    const order = [...segs.map((_, k) => k)]
      .sort((a, b) => (a === state.blend.selectedIdx ? 1 : 0) - (b === state.blend.selectedIdx ? 1 : 0));
    for (const k of order) {
      const dv = blendResult.devices[k];
      const seg = segs[k];
      const isSel = k === state.blend.selectedIdx;
      const color = devColor(k);
      if (!dv) continue;
      for (const r of dv.region) {
        if (r[2] - r[0] <= 1e-6 && r[3] - r[1] > 1e-6) {
          el('line', {
            x1: r[0], y1: r[1], x2: r[2], y2: r[3],
            stroke: color, 'stroke-width': isSel ? 0.07 : 0.05,
            'stroke-linecap': 'round', 'stroke-opacity': isSel ? 0.95 : 0.5,
          }, svg);
        } else {
          el('rect', {
            x: r[0], y: r[1], width: Math.max(0, r[2] - r[0]), height: Math.max(0, r[3] - r[1]),
            fill: color, 'fill-opacity': isSel ? 0.26 : 0.09,
            stroke: color, 'stroke-width': isSel ? 0.02 : 0.01, 'stroke-opacity': isSel ? 0.9 : 0.4,
          }, svg);
        }
      }
      if (isSel && dv.base_rect) {
        const b = dv.base_rect;
        el('rect', {
          x: b[0], y: b[1], width: b[2] - b[0], height: b[3] - b[1], fill: 'none',
          stroke: color, 'stroke-width': 0.016, 'stroke-dasharray': '0.1 0.05', 'stroke-opacity': 0.8,
        }, svg);
      }
      // 区间覆盖光锥
      const p = seg.point;
      if (p) {
        const cxk = segCenterX(seg), hwk = (seg.u1 - seg.u0) / 2;
        el('polygon', {
          points: `${p.x},${p.y} ${cxk - hwk},0 ${cxk + hwk},0`,
          fill: color, 'fill-opacity': 0.07, stroke: color,
          'stroke-width': 0.012, 'stroke-dasharray': '0.07 0.05', 'stroke-opacity': 0.7,
        }, svg);
      }
    }
  }

  drawObstacles(svg);

  // 幕布条 + 邻接重叠带（贴在前墙上）
  const xL = screenLeftX(), xR = xL + s.width;
  el('rect', { x: xL, y: -0.09, width: s.width, height: 0.09, fill: '#1864ab' }, svg);
  if (blendResult && !blendResult.error) {
    for (const ov of blendResult.overlaps) {
      if (ov.value <= 0) continue;
      const k = ov.between[0];
      const a = uToX(segs[k + 1].u0), b = uToX(segs[k].u1);
      if (b - a > 0.001) {
        el('rect', {
          x: a, y: -0.09, width: b - a, height: 0.09,
          fill: ov.ok ? 'url(#ovhatchT)' : '#e03131', 'fill-opacity': ov.ok ? 1 : 0.55,
        }, svg);
      }
    }
  }
  drawScreenCore(svg, s);

  // 覆盖未到/超出的幕布端提示（区间未覆盖整幅幕）
  if (blendResult && !blendResult.error) {
    const u0 = segs[0].u0, u1 = segs[n - 1].u1;
    if (u0 > 1e-6) el('rect', { x: xL, y: -0.16, width: uToX(u0) - xL, height: 0.05, fill: '#e03131' }, svg);
    if (u1 < s.width - 1e-6) el('rect', { x: uToX(u1), y: -0.16, width: xR - uToX(u1), height: 0.05, fill: '#e03131' }, svg);
  }

  // 检修包络 / 机身 / 安装点
  const pairSet = new Set();
  const conflictEnvs = [];
  if (blendResult && blendResult.point_conflicts) {
    for (const c of blendResult.point_conflicts) {
      if (c.type === 'pair') {
        pairSet.add(c.devices.join(','));
        conflictEnvs.push(...c.envelopes);
      }
    }
  }
  if (blendResult && !blendResult.error) {
    for (let k = 0; k < n; k++) {
      const seg = segs[k], dv = blendResult.devices[k];
      const color = devColor(k);
      const p = seg.point;
      if (!p) continue;
      const { body_w: bw, body_d: bd } = seg.scheme;
      const cl = seg.clearance;
      // 检修包络
      const env = [p.x - bw / 2 - cl, p.y - cl, p.x + bw / 2 + cl, p.y + bd + cl];
      const inPair = [...pairSet].some(t => t.split(',').includes(String(k)));
      const selfBad = dv && dv.point && !dv.point.ok;
      el('rect', {
        x: env[0], y: env[1], width: env[2] - env[0], height: env[3] - env[1],
        fill: color, 'fill-opacity': 0.07,
        stroke: inPair ? '#e03131' : color, 'stroke-width': inPair ? 0.03 : 0.016,
        'stroke-dasharray': '0.09 0.05', 'stroke-opacity': inPair ? 0.95 : 0.8,
      }, svg);
      // 机身
      const ok = dv && dv.point && dv.point.ok && !inPair && !selfBad;
      el('rect', {
        x: p.x - bw / 2, y: p.y, width: bw, height: bd,
        fill: ok ? color : '#e03131', 'fill-opacity': ok ? 0.4 : 0.4,
        stroke: ok ? color : '#c92a2a', 'stroke-width': 0.02,
      }, svg);
      // 安装点手柄
      const g = el('g', { class: 'point-handle' }, svg);
      el('circle', { cx: p.x, cy: p.y, r: 0.1, fill: ok ? color : '#e03131', 'fill-opacity': 0.25 }, g);
      el('circle', { cx: p.x, cy: p.y, r: 0.055, fill: '#fff', stroke: ok ? color : '#e03131', 'stroke-width': 0.025 }, g);
      g.addEventListener('pointerdown', e => {
        state.blend.selectedIdx = k;
        startDrag(e, { type: 'bpoint', idx: k });
        render();
      });
      textAt(svg, p.x, p.y - 0.16, `${k + 1}号机`, 0.12, color);
    }
    // 建议点标记（与当前点不同处画 ×）
    if (blendResult.suggested_points) {
      blendResult.suggested_points.forEach((sp, k) => {
        const cp = segs[k].point;
        if (cp && Math.hypot(cp.x - sp.x, cp.y - sp.y) < 0.03) return;
        const c = devColor(k);
        const g = el('g', { class: 'sugg-handle' }, svg);
        el('line', { x1: sp.x - 0.07, y1: sp.y - 0.07, x2: sp.x + 0.07, y2: sp.y + 0.07, stroke: '#2b8a3e', 'stroke-width': 0.025 }, g);
        el('line', { x1: sp.x - 0.07, y1: sp.y + 0.07, x2: sp.x + 0.07, y2: sp.y - 0.07, stroke: '#2b8a3e', 'stroke-width': 0.025 }, g);
        g.addEventListener('pointerdown', e => {
          state.blend.selectedIdx = k;
          startDrag(e, { type: 'bpoint', idx: k });
          segs[k].point = { ...sp };
          render();
        });
      });
    }
  }

  drawDim(svg, 0, D, W, D, 0.42, `房间宽 ${fmt(W)} m`, 'T');
  drawDim(svg, W, 0, W, D, -0.42, `进深 ${fmt(D)} m`, 'T');
}

function renderTop() {
  topSvg.innerHTML = '';
  if (state.mode === 'single') renderTopSingle();
  else renderTopBlend();
}

/* ================= 侧视图（单机） ================= */
const SIDE_PAD = { l: 1.15, t: 0.55, r: 1.05, b: 1.15 };

function renderSideSingle() {
  const svg = sideSvg;
  svg.innerHTML = '';
  const { depth: D, height: H } = state.room;
  const s = state.screen;
  svg.setAttribute('viewBox', `${-SIDE_PAD.l} ${-SIDE_PAD.t} ${D + SIDE_PAD.l + SIDE_PAD.r} ${H + SIDE_PAD.t + SIDE_PAD.b}`);
  addDefs(svg, 'S');
  const Z = z => H - z;

  el('rect', { x: 0, y: 0, width: D, height: H, fill: '#fbfcfd', stroke: '#343a40', 'stroke-width': 0.03 }, svg);
  el('line', { x1: 0, y1: H, x2: D, y2: H, stroke: '#343a40', 'stroke-width': 0.045 }, svg);
  textAt(svg, 0.06, -0.16, '幕布墙', 0.12, '#868e96', 'start');
  textAt(svg, D - 0.06, -0.16, '后墙', 0.12, '#868e96', 'end');
  textAt(svg, D - 0.06, H - 0.12, '地面', 0.11, '#868e96', 'end');

  for (const ob of state.obstacles) {
    el('rect', {
      x: ob.y, y: 0, width: ob.h, height: H,
      fill: 'url(#hatchS)', stroke: '#e03131', 'stroke-width': 0.012, 'stroke-opacity': 0.6,
    }, svg);
    textAt(svg, ob.y + ob.h / 2, 0.14, ob.name, 0.1, '#c92a2a');
  }

  if (result) {
    const ordered = [...result.schemes].sort((a, b) => (a.id === state.selectedSchemeId ? 1 : 0) - (b.id === state.selectedSchemeId ? 1 : 0));
    for (const sr of ordered) {
      const isSel = sr.id === state.selectedSchemeId;
      if (!isSel && !state.showAll) continue;
      if (!sr.ranges.y || !sr.ranges.z) continue;
      const color = colorOf(sr.id);
      const [y1, y2] = sr.ranges.y, [z1, z2] = sr.ranges.z;
      el('rect', {
        x: y1, y: Z(z2), width: Math.max(0, y2 - y1), height: Math.max(0, z2 - z1),
        fill: color, 'fill-opacity': isSel ? 0.26 : 0.09,
        stroke: color, 'stroke-width': isSel ? 0.018 : 0.01,
        'stroke-opacity': isSel ? 0.9 : 0.4,
      }, svg);
    }
  }

  el('rect', { x: -0.06, y: Z(s.bottom + s.height), width: 0.06, height: s.height, fill: '#1864ab' }, svg);
  drawDim(svg, 0, Z(0), 0, Z(s.bottom), -0.3, `下沿 ${fmt(s.bottom)}m`, 'S');
  drawDim(svg, 0, Z(s.bottom), 0, Z(s.bottom + s.height), -0.3, `幕高 ${fmt(s.height)}m`, 'S');

  const sch = currentScheme();
  const sel = resultById[state.selectedSchemeId];
  const p = state.point;
  const hz = state.lensHeight;
  if (sch && sel) {
    const ok = sel.point && sel.point.ok;
    el('line', { x1: p.y, y1: Z(hz), x2: 0, y2: Z(s.bottom + s.height), stroke: '#1971c2', 'stroke-width': 0.014, 'stroke-dasharray': '0.07 0.05' }, svg);
    el('line', { x1: p.y, y1: Z(hz), x2: 0, y2: Z(s.bottom), stroke: '#1971c2', 'stroke-width': 0.014, 'stroke-dasharray': '0.07 0.05' }, svg);
    const body = el('rect', {
      x: p.y, y: Z(hz + sch.body_h / 2), width: sch.body_d, height: sch.body_h,
      fill: ok ? 'rgba(47,158,68,0.45)' : 'rgba(224,49,49,0.45)',
      stroke: ok ? '#2b8a3e' : '#e03131', 'stroke-width': 0.02, class: 'side-body',
    }, svg);
    body.addEventListener('pointerdown', e => startDrag(e, { type: 'sidepoint' }));
    const lens = el('g', { class: 'point-handle' }, svg);
    el('circle', { cx: p.y, cy: Z(hz), r: 0.08, fill: 'rgba(25,113,194,0.3)' }, lens);
    el('circle', { cx: p.y, cy: Z(hz), r: 0.045, fill: '#fff', stroke: '#1971c2', 'stroke-width': 0.022 }, lens);
    lens.addEventListener('pointerdown', e => startDrag(e, { type: 'sidepoint' }));
    textAt(svg, p.y + 0.12, Z(hz) - 0.14, '镜头', 0.11, '#1971c2', 'start');
    drawDim(svg, p.y, Z(0), p.y, Z(hz), 0.3, `h=${fmt(hz)}m`, 'S');
    drawDim(svg, 0, H, p.y, H, 0.38, `L=${fmt(p.y)}m`, 'S');
  }

  drawDim(svg, 0, H, D, H, 0.78, `进深 ${fmt(D)} m`, 'S');
  drawDim(svg, D, 0, D, H, -0.42, `净高 ${H} m`, 'S');
}

/* ================= 侧视图（拼接） ================= */
function renderSideBlend() {
  const svg = sideSvg;
  svg.innerHTML = '';
  const { depth: D, height: H } = state.room;
  const s = state.screen;
  const segs = blendSegs();
  svg.setAttribute('viewBox', `${-SIDE_PAD.l} ${-SIDE_PAD.t} ${D + SIDE_PAD.l + SIDE_PAD.r} ${H + SIDE_PAD.t + SIDE_PAD.b}`);
  addDefs(svg, 'S');
  const Z = z => H - z;

  el('rect', { x: 0, y: 0, width: D, height: H, fill: '#fbfcfd', stroke: '#343a40', 'stroke-width': 0.03 }, svg);
  el('line', { x1: 0, y1: H, x2: D, y2: H, stroke: '#343a40', 'stroke-width': 0.045 }, svg);
  textAt(svg, 0.06, -0.16, '幕布墙', 0.12, '#868e96', 'start');
  textAt(svg, D - 0.06, -0.16, '后墙', 0.12, '#868e96', 'end');

  for (const ob of state.obstacles) {
    el('rect', {
      x: ob.y, y: 0, width: ob.h, height: H,
      fill: 'url(#hatchS)', stroke: '#e03131', 'stroke-width': 0.012, 'stroke-opacity': 0.6,
    }, svg);
    textAt(svg, ob.y + ob.h / 2, 0.14, ob.name, 0.1, '#c92a2a');
  }

  if (blendResult && !blendResult.error) {
    segs.forEach((seg, k) => {
      const dv = blendResult.devices[k];
      if (!dv || !dv.ranges.y || !dv.ranges.z) return;
      const color = devColor(k);
      const isSel = k === state.blend.selectedIdx;
      const [y1, y2] = dv.ranges.y, [z1, z2] = dv.ranges.z;
      el('rect', {
        x: y1, y: Z(z2), width: Math.max(0, y2 - y1), height: Math.max(0, z2 - z1),
        fill: color, 'fill-opacity': isSel ? 0.24 : 0.08,
        stroke: color, 'stroke-width': isSel ? 0.018 : 0.01, 'stroke-opacity': isSel ? 0.9 : 0.35,
      }, svg);
    });
  }

  el('rect', { x: -0.06, y: Z(s.bottom + s.height), width: 0.06, height: s.height, fill: '#1864ab' }, svg);
  drawDim(svg, 0, Z(0), 0, Z(s.bottom), -0.3, `下沿 ${fmt(s.bottom)}m`, 'S');
  drawDim(svg, 0, Z(s.bottom), 0, Z(s.bottom + s.height), -0.3, `幕高 ${fmt(s.height)}m`, 'S');

  if (blendResult && !blendResult.error) {
    segs.forEach((seg, k) => {
      const dv = blendResult.devices[k];
      const p = seg.point;
      if (!dv || !p) return;
      const color = devColor(k);
      const hz = seg.lensZ;
      const selfBad = dv.point && !dv.point.ok;
      const inPair = (blendResult.point_conflicts || []).some(c => c.type === 'pair' && c.devices.includes(k));
      const ok = !selfBad && !inPair;
      const stroke = ok ? color : '#e03131';
      el('line', { x1: p.y, y1: Z(hz), x2: 0, y2: Z(s.bottom + s.height), stroke: color, 'stroke-width': 0.01, 'stroke-dasharray': '0.06 0.05', 'stroke-opacity': 0.6 }, svg);
      el('line', { x1: p.y, y1: Z(hz), x2: 0, y2: Z(s.bottom), stroke: color, 'stroke-width': 0.01, 'stroke-dasharray': '0.06 0.05', 'stroke-opacity': 0.6 }, svg);
      const body = el('rect', {
        x: p.y, y: Z(hz + seg.scheme.body_h / 2), width: seg.scheme.body_d, height: seg.scheme.body_h,
        fill: color, 'fill-opacity': 0.4, stroke, 'stroke-width': k === state.blend.selectedIdx ? 0.025 : 0.015,
        class: 'side-body',
      }, svg);
      body.addEventListener('pointerdown', e => {
        state.blend.selectedIdx = k;
        startDrag(e, { type: 'sidebpoint', idx: k });
        render();
      });
      el('circle', { cx: p.y, cy: Z(hz), r: k === state.blend.selectedIdx ? 0.07 : 0.05, fill: '#fff', stroke, 'stroke-width': 0.02, class: 'point-handle' }, svg)
        .addEventListener('pointerdown', e => {
          state.blend.selectedIdx = k;
          startDrag(e, { type: 'sidebpoint', idx: k });
          render();
        });
      textAt(svg, p.y + 0.1, Z(hz) - 0.12, `${k + 1}号`, 0.1, color, 'start');
    });
  }

  drawDim(svg, 0, H, D, H, 0.78, `进深 ${fmt(D)} m`, 'S');
  drawDim(svg, D, 0, D, H, -0.42, `净高 ${H} m`, 'S');
}

function renderSide() {
  sideSvg.innerHTML = '';
  if (state.mode === 'single') renderSideSingle();
  else renderSideBlend();
}

/* ================= 幕布条带（拼接） ================= */
const STRIP_PAD = { l: 1.7, t: 0.35, r: 0.5, b: 0.5 };

function renderStrip() {
  stripSvg.innerHTML = '';
  if (state.mode !== 'blend') return;
  const s = state.screen;
  const segs = blendSegs();
  const n = segs.length;
  const minU = Math.min(0, ...segs.map(g => g.u0));
  const maxU = Math.max(s.width, ...segs.map(g => g.u1));
  const xLo = uToX(minU), xHi = uToX(maxU);
  const rowH = 0.62, gap = 0.12;
  const totalH = n * rowH + (n - 1) * gap + 0.3;

  // ---- 校准视图数据 ----
  const calOk = calResult && !calResult.error && calResult.status === 'ok';
  const calPrev = calResult && !calResult.error &&
                  calResult.status === 'no_common_attenuation' ? calResult.preview : null;
  const calMissing = calResult && !calResult.error &&
                     calResult.status === 'measurement_missing'
    ? (calResult.missing || []).map(m => m.between[0]) : [];
  const bandSamples = {};     // 左机序号 -> 采样行（含 ok 标记）
  if (calOk) for (const b of calResult.overlaps) bandSamples[b.between[0]] = b.samples;
  if (calPrev) for (const b of calPrev.overlaps) bandSamples[b.between[0]] = b.samples;
  const showProfile = calOk || calPrev;
  const profExtra = showProfile ? 1.25 : 0;

  stripSvg.setAttribute('viewBox',
    `${xLo - STRIP_PAD.l} ${-STRIP_PAD.t} ${xHi - xLo + STRIP_PAD.l + STRIP_PAD.r} ${totalH + profExtra + STRIP_PAD.t + STRIP_PAD.b}`);
  addDefs(stripSvg, 'B');
  // 校准成立时各重叠带的左机→右机渐变填充
  if (calOk) {
    const defs = el('defs', {}, stripSvg);
    for (let k = 0; k < n - 1; k++) {
      const grad = el('linearGradient', { id: `bfade${k}`, x1: 0, y1: 0, x2: 1, y2: 0 }, defs);
      el('stop', { offset: '0%', 'stop-color': devColor(k), 'stop-opacity': 0.5 }, grad);
      el('stop', { offset: '100%', 'stop-color': devColor(k + 1), 'stop-opacity': 0.5 }, grad);
    }
  }

  const topY = 0.05;
  // 整幅幕布底衬
  const xL = screenLeftX(), xR = xL + s.width;
  el('rect', { x: xL, y: topY - 0.02, width: s.width, height: totalH - 0.06, fill: '#eef4fb', stroke: '#1864ab', 'stroke-width': 0.012, 'stroke-dasharray': '0.08 0.05' }, stripSvg);
  textAt(stripSvg, xL, topY - 0.2, '幕左沿 0', 0.11, '#1864ab', 'middle');
  textAt(stripSvg, xR, topY - 0.2, `幕右沿 ${fmt(s.width)}`, 0.11, '#1864ab', 'middle');

  segs.forEach((seg, k) => {
    const y = topY + k * (rowH + gap);
    const a = uToX(seg.u0), b = uToX(seg.u1);
    const color = devColor(k);
    const isSel = k === state.blend.selectedIdx;
    const dv = blendResult && blendResult.devices ? blendResult.devices[k] : null;
    const feasible = dv && dv.feasible;

    // 行标签
    const lab = el('text', {
      x: xLo - 0.12, y: y + rowH / 2, 'font-size': 0.13, fill: color,
      'text-anchor': 'end', 'dominant-baseline': 'middle', class: 'halo',
      'font-weight': '600',
    }, stripSvg);
    lab.textContent = `${k + 1}号机`;

    // 区间条
    el('rect', {
      x: a, y: y + 0.1, width: Math.max(0.02, b - a), height: rowH - 0.2,
      fill: color, 'fill-opacity': isSel ? 0.33 : 0.18,
      stroke: feasible === false ? '#e03131' : color,
      'stroke-width': isSel ? 0.025 : 0.015, rx: 0.03,
      class: 'strip-row',
    }, stripSvg).addEventListener('click', () => {
      state.blend.selectedIdx = k;
      render();
    });

    // 邻接重叠（融合带）
    if (k < n - 1) {
      const ovA = uToX(segs[k + 1].u0), ovB = uToX(seg.u1);
      const ov = segs[k].u1 - segs[k + 1].u0;
      if (ov > 0) {
        const need = Math.max(seg.min_overlap, segs[k + 1].min_overlap);
        const ovOk = ov + 1e-6 >= need;
        const bandY = y + 0.1, bandH = (rowH - 0.2) * 2 + gap;
        el('rect', {
          x: ovA, y: bandY, width: ovB - ovA, height: bandH,
          fill: calOk ? `url(#bfade${k})` : (ovOk ? 'url(#ovhatchB)' : '#e03131'),
          'fill-opacity': calOk || ovOk ? 1 : 0.35,
        }, stripSvg);
        textAt(stripSvg, (ovA + ovB) / 2, y + rowH + gap / 2,
          `重叠 ${fmt(ov)}m${ovOk ? '' : ` < ${fmt(need)}`}`, 0.105,
          ovOk ? '#2b8a3e' : '#c92a2a');
        // 校准采样点（绿=达标，红=超差）
        const rows = bandSamples[k] || [];
        const cy = bandY + bandH / 2;
        for (const sm of rows) {
          const dot = el('circle', {
            cx: uToX(sm.u), cy, r: 0.05,
            fill: sm.ok ? '#2b8a3e' : '#e03131',
            stroke: '#fff', 'stroke-width': 0.015,
          }, stripSvg);
          const tt = el('title', {}, dot);
          tt.textContent = `u=${fmt(sm.u)}m 预测叠加 ${fmt(sm.total, 1)}` +
            (sm.ok ? '（达标）' : '（超差）');
        }
        if (calMissing.includes(k)) {
          textAt(stripSvg, (ovA + ovB) / 2, cy, '缺采样', 0.11, '#c92a2a');
        }
      } else if (ov < 0) {
        // 缝隙
        el('rect', { x: ovB, y: y + 0.08, width: ovA - ovB, height: rowH - 0.16, fill: '#e03131', 'fill-opacity': 0.5 }, stripSvg);
        textAt(stripSvg, (ovA + ovB) / 2, y + rowH / 2, `缝 ${fmt(-ov)}m`, 0.1, '#fff');
      }
    }

    // 宽度/区间标注（校准成立时附衰减值）
    const attTxt = calOk && calResult.attenuations[k]
      ? `　衰减 ${fmt(calResult.attenuations[k].value, 3)}` : '';
    textAt(stripSvg, (a + b) / 2, y + rowH / 2 + 0.02,
      `区间宽 ${fmt(seg.u1 - seg.u0)}m　净距 ${fmt(seg.clearance)}m${attTxt}`, 0.115,
      feasible === false ? '#c92a2a' : '#343a40');
    textAt(stripSvg, a, y + rowH + 0.06, fmt(seg.u0), 0.095, '#868e96');
    textAt(stripSvg, b, y + rowH + 0.06, fmt(seg.u1), 0.095, '#868e96');

    // 端点手柄（三角，可拖）
    const mkHandle = (hx, which) => {
      const g = el('g', { class: 'strip-handle' }, stripSvg);
      el('polygon', {
        points: `${hx},${y + 0.02} ${hx - 0.08},${y - 0.1} ${hx + 0.08},${y - 0.1}`,
        fill: '#fff', stroke: color, 'stroke-width': 0.02,
      }, g);
      g.addEventListener('pointerdown', e => {
        state.blend.selectedIdx = k;
        startDrag(e, { type: `strip${which}`, idx: k });
        render();
      });
    };
    mkHandle(a, 0);
    const g2 = el('g', { class: 'strip-handle' }, stripSvg);
    el('polygon', {
      points: `${b},${y + rowH - 0.02} ${b - 0.08},${y + rowH + 0.1} ${b + 0.08},${y + rowH + 0.1}`,
      fill: '#fff', stroke: color, 'stroke-width': 0.02,
    }, g2);
    g2.addEventListener('pointerdown', e => {
      state.blend.selectedIdx = k;
      startDrag(e, { type: 'strip1', idx: k });
      render();
    });
  });

  // ---- 逐点预测亮度曲线（校准成立或诊断预览时）----
  if (showProfile) drawCalProfile(xL, xR, xLo, totalH, calOk, calPrev, segs);
}

function drawCalProfile(xL, xR, xLo, totalH, calOk, calPrev, segs) {
  const s = state.screen;
  const T = calResult.target.luminance, tol = calResult.target.tolerance;
  const profTop = totalH + 0.22, profH = 0.78;
  // 数据点：ok 时用逐点预测；诊断预览时用各采样叠加值 + 各机非重叠区参考线
  let pts = [];
  if (calOk) {
    pts = calResult.screen_samples.map(p => ({ u: p.u, v: p.luminance, ok: p.ok }));
  } else {
    for (const b of calPrev.overlaps) {
      for (const sm of b.samples) pts.push({ u: sm.u, v: sm.total, ok: sm.ok });
    }
  }
  const levels = calOk
    ? calResult.attenuations.map(a => ({ device: a.device, v: a.non_overlap_luminance, ok: a.ok }))
    : calPrev.levels.map(l => ({ device: l.device, v: l.luminance, ok: l.ok }));
  const allV = [...pts.map(p => p.v), ...levels.map(l => l.v), T - tol, T + tol];
  const vLo = Math.min(...allV) - Math.max(1, tol * 0.25);
  const vHi = Math.max(...allV) + Math.max(1, tol * 0.25);
  const Y = v => profTop + profH - (v - vLo) / (vHi - vLo) * profH;

  textAt(stripSvg, xLo - 0.12, profTop - 0.08, '预测亮度', 0.1, '#495057', 'end');
  // 目标容差带
  el('rect', {
    x: xL, y: Y(T + tol), width: s.width, height: Y(T - tol) - Y(T + tol),
    fill: 'rgba(47,158,68,0.10)', stroke: 'none',
  }, stripSvg);
  for (const [v, lbl] of [[T + tol, `上限 ${fmt(T + tol, 0)}`],
                          [T, `目标 ${fmt(T, 0)}`],
                          [T - tol, `下限 ${fmt(T - tol, 0)}`]]) {
    el('line', {
      x1: xL, y1: Y(v), x2: xR, y2: Y(v),
      stroke: v === T ? '#2b8a3e' : '#87c78f',
      'stroke-width': v === T ? 0.014 : 0.01,
      'stroke-dasharray': v === T ? 'none' : '0.07 0.05',
    }, stripSvg);
    textAt(stripSvg, xLo - 0.1, Y(v), lbl, 0.09, '#2b8a3e', 'end');
  }
  // 各机非重叠区参考亮度（虚线段）
  const n = segs.length;
  levels.forEach(lv => {
    const k = lv.device;
    const loEx = k === 0 ? segs[0].u0 : Math.max(segs[k].u0, segs[k - 1].u1);
    const hiEx = k === n - 1 ? segs[k].u1 : Math.min(segs[k].u1, segs[k + 1].u0);
    const a = uToX(Math.max(loEx, 0)), b = uToX(Math.min(hiEx, s.width));
    if (b - a <= 0.01) return;
    el('line', {
      x1: a, y1: Y(lv.v), x2: b, y2: Y(lv.v),
      stroke: devColor(k), 'stroke-width': 0.02, 'stroke-dasharray': '0.09 0.05',
      'stroke-opacity': 0.85,
    }, stripSvg);
  });
  // 逐点预测折线与采样点
  if (calOk && pts.length > 1) {
    el('polyline', {
      points: pts.map(p => `${uToX(p.u)},${Y(p.v)}`).join(' '),
      fill: 'none', stroke: '#1971c2', 'stroke-width': 0.02,
    }, stripSvg);
  }
  for (const p of pts) {
    el('circle', {
      cx: uToX(p.u), cy: Y(p.v), r: 0.045,
      fill: p.ok ? '#2b8a3e' : '#e03131', stroke: '#fff', 'stroke-width': 0.012,
    }, stripSvg);
  }
}

/* ================= 面板：单机方案列表 ================= */
function renderSchemeList() {
  const ul = document.getElementById('schemeList');
  ul.innerHTML = '';
  const items = state.schemes.map(sch => ({ sch, r: resultById[sch.id] }));
  const rankOf = r => (!r || !r.feasible) ? 2 : (r.domain === 'line' ? 1 : 0);
  const metricOf = r => (!r || !r.feasible) ? 0 : (r.domain === 'line' ? r.line_length : r.area);
  items.sort((a, b) => {
    const ra = rankOf(a.r), rb = rankOf(b.r);
    if (ra !== rb) return ra - rb;
    return metricOf(b.r) - metricOf(a.r);
  });
  items.forEach(({ sch, r }, i) => {
    const li = document.createElement('li');
    li.className = 'scheme-item' + (sch.id === state.selectedSchemeId ? ' selected' : '');
    const feasible = r && r.feasible;
    let areaTxt;
    if (!r) areaTxt = '…';
    else if (feasible && r.domain === 'line') areaTxt = `安装线 ${fmt(r.line_length)} m`;
    else if (feasible) areaTxt = `${fmt(r.area)} m²`;
    else areaTxt = '不可行';
    li.innerHTML =
      `<span class="rank">${i + 1}</span>` +
      `<span class="chip" style="background:${colorOf(sch.id)}"></span>` +
      `<span class="name" title="${esc(sch.name)}">${esc(sch.name)}</span>` +
      `<span class="tr">TR ${sch.tr_min}–${sch.tr_max}</span>` +
      `<span class="area ${feasible ? '' : 'bad'}">${areaTxt}</span>`;
    if (r && !feasible && r.diagnostics.length) li.title = r.diagnostics.join('\n');
    li.addEventListener('click', () => { state.selectedSchemeId = sch.id; onStateChange(); });
    ul.appendChild(li);
  });
  document.getElementById('delSchemeBtn').disabled = state.schemes.length <= 1;
  document.getElementById('schemeEditorCard').style.display = currentScheme() ? '' : 'none';
}

/* ================= 面板：拼接设备列表 ================= */
function renderBlendList() {
  const ul = document.getElementById('blendList');
  ul.innerHTML = '';
  const calOk = calResult && !calResult.error && calResult.status === 'ok';
  blendSegs().forEach((seg, k) => {
    const dv = blendDeviceResult(k);
    const li = document.createElement('li');
    li.className = 'scheme-item' + (k === state.blend.selectedIdx ? ' selected' : '');
    let stTxt = '…';
    if (dv) {
      if (!dv.feasible) stTxt = '不可行';
      else if (dv.domain === 'line') stTxt = `安装线 ${fmt(dv.line_length)}m`;
      else stTxt = `${fmt(dv.area)} m²`;
    }
    if (calOk && calResult.attenuations[k]) {
      stTxt += ` · 衰减 ${fmt(calResult.attenuations[k].value, 3)}`;
    }
    const ovTxt = k < blendSegs().length - 1
      ? `重叠 ${fmt(Math.max(0, seg.u1 - blendSegs()[k + 1].u0))}m` : '';
    li.innerHTML =
      `<span class="rank" style="background:${devColor(k)}">${k + 1}</span>` +
      `<span class="name" title="${esc(seg.scheme.name)}">${esc(seg.scheme.name)}</span>` +
      `<span class="tr">${ovTxt}</span>` +
      `<span class="area ${dv && !dv.feasible ? 'bad' : ''}">${stTxt}</span>`;
    if (dv && !dv.feasible) li.title = dv.diagnostics.join('\n');
    li.addEventListener('click', () => { state.blend.selectedIdx = k; render(); });
    ul.appendChild(li);
  });
}

function renderObstacleList() {
  const ul = document.getElementById('obstacleList');
  ul.innerHTML = '';
  for (const ob of state.obstacles) {
    const li = document.createElement('li');
    li.className = 'ob-item' + (ob.id === state.selectedObstacleId ? ' selected' : '');
    li.innerHTML = `<span class="ob-dot"></span><span>${esc(ob.name)}</span>` +
      `<span class="dim">${fmt(ob.w)}×${fmt(ob.h)}m @ (${fmt(ob.x)}, ${fmt(ob.y)})</span>`;
    li.addEventListener('click', () => { state.selectedObstacleId = ob.id; render(); });
    ul.appendChild(li);
  }
  if (!state.obstacles.length) {
    const li = document.createElement('li');
    li.className = 'hint';
    li.textContent = '暂无禁装区';
    ul.appendChild(li);
  }
  document.getElementById('delObstacleBtn').disabled = !state.selectedObstacleId;
}

/* ================= 面板：选点信息（单机） ================= */
function renderPointInfoSingle() {
  const box = document.getElementById('pointInfo');
  const sch = currentScheme();
  const sel = resultById[state.selectedSchemeId];
  if (!sch || !sel) {
    box.innerHTML = '<h2>选点与约束</h2><p class="hint">请添加并选择镜头方案</p>';
    return;
  }
  let html = `<h2>选点与约束 — ${esc(sel.name)}</h2>`;
  if (sel.diagnostics.length) {
    html += `<div class="diag-box"><b>⚠ 可安装区域为空，冲突约束：</b><ul>` +
      sel.diagnostics.map(d => `<li>${esc(d)}</li>`).join('') + '</ul></div>';
  } else if (sel.feasible) {
    if (sel.domain === 'line') {
      html += `<div class="ok-box">✅ 水平位移为 0，退化为固定 x=<b>${fmt(sel.base_rect[0])}m</b> 的安装线，` +
        `扣除禁装区后可行纵深合计 <b>${fmt(sel.line_length)} m</b>（面积为 0 但仍可沿线安放）</div>`;
    } else {
      html += `<div class="ok-box">✅ 可安装区域面积 <b>${fmt(sel.area)} m²</b>（镜头位置）</div>`;
    }
  }
  const p = sel.point;
  if (p) {
    const zr = sel.ranges.z;
    const rows = [
      ['投射距离', p.checks.throw,
        `L=${fmt(p.throw_distance)}m → 投射比 ${fmt(p.throw_ratio)}（要求 ${sch.tr_min}–${sch.tr_max}）`],
      ['水平位移', p.checks.shift,
        `偏移 ${fmt(p.h_shift_used * state.screen.width)}m＝${fmt(p.h_shift_used * 100, 0)}% 幕宽（允许 ±${fmt(sch.h_shift * 100, 0)}%）`],
      ['墙面余量', p.checks.wall,
        p.checks.wall ? '机身与四墙余量满足' : '机身越出墙面余量边界'],
      ['机身避障', p.checks.obstacle,
        p.checks.obstacle ? '未触碰禁装区' : `与禁装区「${esc(p.obstacle_hit || '')}」相交`],
      ['镜头高度', p.checks.height,
        `h=${fmt(p.z)}m＝位移 ${fmt(p.v_shift_used * 100, 0)}% 幕高` +
        (zr ? `（允许 ${fmt(zr[0])}–${fmt(zr[1])}m）` : '（垂直方向无解）')],
    ];
    html += '<table class="checks">' + rows.map(([name, ok, txt]) =>
      `<tr><td class="ico">${ok ? '✅' : '❌'}</td><td class="cname">${name}</td><td>${txt}</td></tr>`).join('') +
      '</table>';
    html += p.ok
      ? '<div class="ok-box">✅ 当前选点可安装</div>'
      : '<div class="diag-box">❌ 当前选点不可安装（见上方 ✗ 项）</div>';
  }
  box.innerHTML = html;
}

/* ================= 面板：联合状态（拼接） ================= */
function renderPointInfoBlend() {
  const box = document.getElementById('pointInfo');
  const segs = blendSegs();
  let html = '<h2>拼接联合状态</h2>';

  if (blendResult && blendResult.error) {
    html += `<div class="diag-box">❌ ${esc(blendResult.error)}</div>`;
    box.innerHTML = html;
    return;
  }
  if (!blendResult) {
    box.innerHTML = html + '<p class="hint">计算中…</p>';
    return;
  }

  const st = blendResult.status;
  const banner = {
    ok: ['ok-box', '✅ 联合可行：存在一组安装点，使覆盖连续、邻接重叠达标、检修包络彼此及与禁装区均不相交'],
    joint_conflict: ['diag-box', '⚠ 当前安装点存在冲突（顶视图 × 为服务器给出的可行建议点，可直接点击或拖动采纳）'],
    device_infeasible: ['diag-box', '❌ 存在设备无可行安装域，未保存部分方案——请先解决下列设备级冲突'],
    interval_invalid: ['diag-box', '❌ 覆盖区间约束不成立（未连续覆盖、重叠不足或区间无序），未保存部分方案'],
    joint_infeasible: ['diag-box', '❌ 各机单独可行，但联合约束冲突：不存在一组安装点使检修包络同时互避，未保存部分方案'],
  }[st] || ['diag-box', st];
  html += `<div class="${banner[0]}">${banner[1]}</div>`;

  if (blendResult.diagnostics.length) {
    html += '<div class="diag-box" style="margin-top:6px"><b>诊断（设备 · 区间 · 冲突来源）：</b><ul>' +
      blendResult.diagnostics.map(d => `<li>${esc(d)}</li>`).join('') + '</ul></div>';
  }

  // 邻接重叠
  if (blendResult.overlaps.length) {
    html += '<table class="checks"><tr><td class="cname">邻接</td><td>重叠 / 要求</td><td></td></tr>';
    for (const ov of blendResult.overlaps) {
      html += `<tr><td class="ico">${ov.ok ? '✅' : '❌'}</td>` +
        `<td class="cname">${ov.between[0] + 1}↔${ov.between[1] + 1}</td>` +
        `<td>${fmt(ov.value)}m / ${fmt(ov.required)}m</td></tr>`;
    }
    html += '</table>';
  }

  // 每台设备校验
  html += '<table class="checks">';
  blendResult.devices.forEach((dv, k) => {
    const seg = segs[k];
    const color = devColor(k);
    const p = dv.point;
    const inPair = (blendResult.point_conflicts || []).some(c => c.type === 'pair' && c.devices.includes(k));
    const ok = dv.feasible && p && p.ok && !inPair;
    html += `<tr><td class="ico"><span style="color:${color};font-weight:700">${k + 1}</span></td>` +
      `<td class="cname" style="color:${color}">${esc(seg.scheme.name)}</td>` +
      `<td>区间 [${fmt(seg.u0)}, ${fmt(seg.u1)}]m，宽 ${fmt(seg.u1 - seg.u0)}m，` +
      `TR ${seg.scheme.tr_min}–${seg.scheme.tr_max}，净距 ${fmt(seg.clearance)}m` +
      (dv.feasible
        ? (dv.domain === 'line' ? `，安装线 ${fmt(dv.line_length)}m` : `，域 ${fmt(dv.area)}m²`)
        : '，<b style="color:#c92a2a">无可行域</b>') +
      (p ? `，L=${fmt(p.throw_distance)}m，h=${fmt(seg.lensZ)}m ${ok ? '✅' : '❌'}` : '') +
      (inPair ? ' <b style="color:#c92a2a">检修包络与邻机相交</b>' : '') +
      '</td></tr>';
    if (!dv.feasible) {
      for (const d of dv.diagnostics) html += `<tr><td></td><td></td><td class="hint" style="color:#a61e1e">${esc(d)}</td></tr>`;
    } else if (p && !p.ok) {
      const bad = Object.entries(p.checks).filter(([, v]) => !v).map(([kk]) =>
        ({ throw: '投射距离', shift: '水平位移', wall: '墙面余量', obstacle: '避障/净距', height: '镜头高度' }[kk]));
      html += `<tr><td></td><td></td><td class="hint" style="color:#a61e1e">当前点不满足：${bad.join('、')}${p.obstacle_hit ? `（${esc(p.obstacle_hit)}）` : ''}</td></tr>`;
    }
  });
  html += '</table>';

  if (blendResult.suggested_points &&
      ['ok', 'joint_conflict'].includes(blendResult.status)) {
    const allMatch = segs.every((seg, k) => {
      const sp = blendResult.suggested_points[k];
      return seg.point && Math.hypot(seg.point.x - sp.x, seg.point.y - sp.y) < 0.03;
    });
    html += allMatch
      ? '<div class="ok-box" style="margin-top:6px">✅ 当前各安装点即为联合可行解</div>'
      : '<button id="adoptBtn" class="wide" style="margin-top:6px">⤷ 采纳服务器建议安装点</button>';
  }
  box.innerHTML = html;
  const btn = document.getElementById('adoptBtn');
  if (btn) btn.addEventListener('click', () => adoptSuggested(true));
}

/* ================= 面板：画面融合校准（拼接） ================= */
let calEditorSig = null;          // 校准编辑器结构签名（变化时才重建 DOM，避免输入失焦）

function calStructSig() {
  const segs = blendSegs();
  return JSON.stringify([
    segs.map(s => s.id + ':' + s.scheme.name),
    segs.slice(0, -1).map((_, k) =>
      bandRangeOf(k).map(v => v.toFixed(3)).join('-') +
      ':' + (state.calBands[String(k)] || []).length),
  ]);
}

function bandRangeOf(k) {
  const segs = blendSegs();
  return [segs[k + 1].u0, segs[k].u1];   // 重叠带 [u0, u1]（幕布坐标）
}

function buildCalEditors() {
  const segs = blendSegs();
  // ---- 逐机测量行 ----
  const devBox = document.getElementById('calDeviceList');
  devBox.innerHTML = '<h3>逐机测量（实测基准亮度 · 可调衰减上下限）</h3>';
  segs.forEach((seg, k) => {
    const row = document.createElement('div');
    row.className = 'cal-row';
    row.innerHTML =
      `<span class="cal-dev" style="color:${devColor(k)}">${k + 1}号机</span>` +
      '<label>基准亮度<input type="number" step="1" min="0.01"></label>' +
      '<label>衰减下限<input type="number" step="0.01" min="0" max="1"></label>' +
      '<label>衰减上限<input type="number" step="0.01" min="0" max="1"></label>';
    const [base, lo, hi] = row.querySelectorAll('input');
    base.dataset.cal = `base:${k}`; lo.dataset.cal = `attMin:${k}`; hi.dataset.cal = `attMax:${k}`;
    base.addEventListener('input', () => {
      const v = parseFloat(base.value);
      if (Number.isFinite(v)) { seg.cal.base = v; onStateChange(); }
    });
    lo.addEventListener('input', () => {
      const v = parseFloat(lo.value);
      if (Number.isFinite(v)) { seg.cal.attMin = v; onStateChange(); }
    });
    hi.addEventListener('input', () => {
      const v = parseFloat(hi.value);
      if (Number.isFinite(v)) { seg.cal.attMax = v; onStateChange(); }
    });
    devBox.appendChild(row);
  });

  // ---- 重叠带采样编辑器 ----
  const bandBox = document.getElementById('calBandList');
  bandBox.innerHTML = '<h3>重叠带两侧亮度采样（沿幕布坐标）</h3>';
  for (let k = 0; k < segs.length - 1; k++) {
    const [u0, u1] = bandRangeOf(k);
    const wrap = document.createElement('div');
    wrap.className = 'cal-band';
    const head = document.createElement('div');
    head.className = 'cal-band-head';
    head.innerHTML =
      `<span style="color:${devColor(k)}">●</span><span style="color:${devColor(k + 1)}">●</span> ` +
      `重叠带 ${k + 1}（${k + 1}号机↔${k + 2}号机，[${fmt(u0)}, ${fmt(u1)}]m）`;
    const addBtn = document.createElement('button');
    addBtn.className = 'mini';
    addBtn.textContent = '＋ 添加采样点';
    addBtn.addEventListener('click', () => {
      const key = String(k);
      const list = state.calBands[key] = state.calBands[key] || [];
      const [a, b] = bandRangeOf(k);
      list.push({ u: (a + b) / 2, left: segs[k].cal.base, right: segs[k + 1].cal.base });
      onStateChange();
    });
    head.appendChild(addBtn);
    wrap.appendChild(head);

    const samples = state.calBands[String(k)] || [];
    if (!samples.length) {
      const p = document.createElement('p');
      p.className = 'hint warn';
      p.textContent = '尚未录入采样——该校准带测量缺失，系统不会输出校准结果';
      wrap.appendChild(p);
    }
    samples.forEach((smp, si) => {
      const row = document.createElement('div');
      row.className = 'cal-row cal-sample';
      row.innerHTML =
        '<label>u (m)<input type="number" step="0.01"></label>' +
        `<label>${k + 1}号机亮度<input type="number" step="1" min="0"></label>` +
        `<label>${k + 2}号机亮度<input type="number" step="1" min="0"></label>` +
        '<button class="mini danger" title="删除该采样点">×</button>';
      const [iu, il, ir] = row.querySelectorAll('input');
      iu.dataset.cal = `su:${k}:${si}`; il.dataset.cal = `sl:${k}:${si}`;
      ir.dataset.cal = `sr:${k}:${si}`;
      iu.addEventListener('input', () => {
        const v = parseFloat(iu.value);
        if (Number.isFinite(v)) { smp.u = v; onStateChange(); }
      });
      il.addEventListener('input', () => {
        const v = parseFloat(il.value);
        if (Number.isFinite(v)) { smp.left = v; onStateChange(); }
      });
      ir.addEventListener('input', () => {
        const v = parseFloat(ir.value);
        if (Number.isFinite(v)) { smp.right = v; onStateChange(); }
      });
      row.querySelector('button').addEventListener('click', () => {
        state.calBands[String(k)].splice(si, 1);
        onStateChange();
      });
      wrap.appendChild(row);
    });
    bandBox.appendChild(wrap);
  }
}

function syncCalInputs() {
  const segs = blendSegs();
  document.querySelectorAll('#calCard input[data-cal]').forEach(input => {
    if (document.activeElement === input) return;
    const [kind, a, b] = input.dataset.cal.split(':');
    const k = Number(a);
    let v = '';
    if (kind === 'base') v = segs[k] ? segs[k].cal.base : '';
    else if (kind === 'attMin') v = segs[k] ? segs[k].cal.attMin : '';
    else if (kind === 'attMax') v = segs[k] ? segs[k].cal.attMax : '';
    else {
      const smp = (state.calBands[String(k)] || [])[Number(b)];
      if (smp) v = kind === 'su' ? smp.u : kind === 'sl' ? smp.left : smp.right;
    }
    input.value = v === '' ? '' : fmt(v, kind === 'su' ? 2 : (kind.startsWith('att') ? 2 : 1));
  });
}

function renderCalResult() {
  const box = document.getElementById('calResult');
  if (!calResult) {
    box.innerHTML = '<p class="hint">校准计算中…</p>';
    return;
  }
  if (calResult.error) {
    box.innerHTML = `<div class="diag-box">❌ ${esc(calResult.error)}</div>`;
    return;
  }
  const banners = {
    ok: ['ok-box', '✅ 校准成立：各机衰减全局一致，非重叠区与重叠带的加权亮度均落入目标容差'],
    measurement_missing: ['diag-box', '⚠ 测量缺失：请补齐下列重叠带的两侧亮度采样，补齐前不输出校准'],
    no_common_attenuation: ['diag-box', '❌ 衰减范围无共同解，未输出校准（幕布条带中的红点为超差采样）'],
    blend_interval_invalid: ['diag-box', '❌ 原拼接覆盖区间不合法，校准未执行'],
    blend_device_infeasible: ['diag-box', '❌ 原拼接存在设备无可行安装域，校准未执行'],
    blend_joint_infeasible: ['diag-box', '❌ 原拼接联合约束冲突，校准未执行'],
    blend_joint_conflict: ['diag-box', '⚠ 当前安装点与拼接联合约束冲突，校准未执行（可先采纳服务器建议点）'],
  };
  const [cls, msg] = banners[calResult.status] || ['diag-box', calResult.status];
  let html = `<div class="${cls}">${msg}</div>`;
  if (calResult.diagnostics && calResult.diagnostics.length) {
    html += '<div class="diag-box" style="margin-top:6px"><b>诊断：</b><ul>' +
      calResult.diagnostics.map(d => `<li>${esc(d)}</li>`).join('') + '</ul></div>';
  }
  if (calResult.status === 'ok') {
    const T = calResult.target;
    html += `<table class="checks"><tr><td class="cname">设备</td>` +
      `<td>衰减值（范围）</td><td>基准亮度</td><td>非重叠区亮度 / 目标 ${fmt(T.luminance, 1)}±${fmt(T.tolerance, 1)}</td></tr>`;
    for (const a of calResult.attenuations) {
      html += `<tr><td class="ico"><span style="color:${devColor(a.device)};font-weight:700">${a.device + 1}</span></td>` +
        `<td class="cname"><b>${fmt(a.value, 4)}</b>（${fmt(a.range[0], 2)}–${fmt(a.range[1], 2)}）</td>` +
        `<td>${fmt(a.base_luminance, 1)}</td><td>${fmt(a.non_overlap_luminance, 1)} ✅</td></tr>`;
    }
    html += '</table>';
    for (const band of calResult.overlaps) {
      html += `<p class="hint">重叠带 ${band.between[0] + 1}（[${fmt(band.u0)}, ${fmt(band.u1)}]m）` +
        `渐变权重：左端 左${fmt(band.weights.u0.left, 2)}/右${fmt(band.weights.u0.right, 2)} → ` +
        `右端 左${fmt(band.weights.u1.left, 2)}/右${fmt(band.weights.u1.right, 2)}，` +
        `${band.samples.length} 个采样点全部达标 ✅</p>`;
    }
  }
  box.innerHTML = html;
}

function renderCalPanel() {
  const sig = calStructSig();
  if (sig !== calEditorSig) {
    buildCalEditors();
    calEditorSig = sig;
  }
  syncCalInputs();
  renderCalResult();
}

/* ================= 输入绑定 ================= */
const numBindings = [];
function bindNum(id, get, set, digits = 2) {
  const input = document.getElementById(id);
  input.addEventListener('input', () => {
    const v = parseFloat(input.value);
    if (Number.isFinite(v)) { set(v); onStateChange(); }
  });
  numBindings.push([input, get, digits]);
}

function syncInputs() {
  for (const [input, get, digits] of numBindings) {
    if (document.activeElement !== input) {
      const v = get();
      input.value = v === null || v === undefined ? '' : fmt(v, digits);
    }
  }
  const sch = currentScheme();
  document.getElementById('schName').value = sch ? sch.name : '';
  const slider = document.getElementById('lensHeight');
  const sel = resultById[state.selectedSchemeId];
  const lo = sel && sel.ranges.z ? sel.ranges.z[0] : 0;
  const hi = sel && sel.ranges.z ? sel.ranges.z[1] : state.room.height;
  slider.min = lo.toFixed(2);
  slider.max = hi.toFixed(2);
  if (document.activeElement !== slider) slider.value = state.lensHeight;
  document.getElementById('lensHeightVal').textContent = fmt(state.lensHeight) + ' m';
  const hint = document.getElementById('lensHeightHint');
  if (sel && sel.ranges.z) {
    hint.textContent = `允许 ${fmt(lo)}–${fmt(hi)} m（幕布中心 ${fmt(sel.derived.sc)}m，垂直位移 ±${fmt(sch.v_shift * 100, 0)}%）`;
    hint.className = 'hint';
  } else if (sel) {
    hint.textContent = '⚠ 该方案垂直方向无可行高度';
    hint.className = 'hint warn';
  } else {
    hint.textContent = '';
  }

  // 拼接编辑卡
  const seg = currentSeg();
  document.getElementById('bschName').value = seg ? seg.scheme.name : '';
  const bh = document.getElementById('bschHint');
  if (seg && blendResult) {
    const k = state.blend.selectedIdx;
    const dv = blendDeviceResult(k);
    document.getElementById('blendEditorTitle').textContent = `${k + 1} 号机参数（覆盖 ${fmt(seg.u0)}–${fmt(seg.u1)}m）`;
    if (dv && dv.ranges && dv.ranges.z) {
      bh.textContent = `镜头高度允许 ${fmt(dv.ranges.z[0])}–${fmt(dv.ranges.z[1])}m（区间宽 ${fmt(seg.u1 - seg.u0)}m，区间中心 x=${fmt(segCenterX(seg))}m）`;
      bh.className = 'hint';
    } else if (dv) {
      bh.textContent = '⚠ 该设备垂直方向无可行高度';
      bh.className = 'hint warn';
    }
  }
}

function bindAllInputs() {
  const R = () => state.room, S = () => state.screen, B = () => currentSeg();
  bindNum('roomWidth', () => R().width, v => R().width = v);
  bindNum('roomDepth', () => R().depth, v => R().depth = v);
  bindNum('roomHeight', () => R().height, v => R().height = v);
  bindNum('roomMargin', () => R().margin, v => R().margin = v);
  bindNum('screenWidth', () => S().width, v => S().width = v);
  bindNum('screenHeight', () => S().height, v => S().height = v);
  bindNum('screenBottom', () => S().bottom, v => S().bottom = v);
  bindNum('screenCx', () => S().cx, v => S().cx = v);
  bindNum('schTrMin', () => currentScheme()?.tr_min ?? 0, v => { const s = currentScheme(); if (s) s.tr_min = v; });
  bindNum('schTrMax', () => currentScheme()?.tr_max ?? 0, v => { const s = currentScheme(); if (s) s.tr_max = v; });
  bindNum('schHShift', () => (currentScheme()?.h_shift ?? 0) * 100, v => { const s = currentScheme(); if (s) s.h_shift = v / 100; }, 0);
  bindNum('schVShift', () => (currentScheme()?.v_shift ?? 0) * 100, v => { const s = currentScheme(); if (s) s.v_shift = v / 100; }, 0);
  bindNum('schBodyW', () => currentScheme()?.body_w ?? 0, v => { const s = currentScheme(); if (s) s.body_w = v; });
  bindNum('schBodyD', () => currentScheme()?.body_d ?? 0, v => { const s = currentScheme(); if (s) s.body_d = v; });
  bindNum('schBodyH', () => currentScheme()?.body_h ?? 0, v => { const s = currentScheme(); if (s) s.body_h = v; });

  document.getElementById('schName').addEventListener('input', e => {
    const s = currentScheme();
    if (s) { s.name = e.target.value; renderSchemeList(); scheduleCompute(); }
  });
  document.getElementById('lensHeight').addEventListener('input', e => {
    const v = parseFloat(e.target.value);
    if (Number.isFinite(v)) { state.lensHeight = v; onStateChange(); }
  });
  document.getElementById('showAll').addEventListener('change', e => {
    state.showAll = e.target.checked;
    render();
  });
  document.getElementById('addSchemeBtn').addEventListener('click', () => {
    const s = {
      id: uid(), name: `方案 ${state.schemes.length + 1}`,
      tr_min: 1.2, tr_max: 1.9, h_shift: 0.25, v_shift: 0.4,
      body_w: 0.4, body_d: 0.32, body_h: 0.15,
    };
    state.schemes.push(s);
    state.selectedSchemeId = s.id;
    onStateChange();
  });
  document.getElementById('delSchemeBtn').addEventListener('click', () => {
    if (state.schemes.length <= 1) return;
    state.schemes = state.schemes.filter(s => s.id !== state.selectedSchemeId);
    state.selectedSchemeId = state.schemes[0].id;
    onStateChange();
  });

  /* ---- 模式切换 ---- */
  document.getElementById('modeSingle').addEventListener('click', enterSingleMode);
  document.getElementById('modeBlend').addEventListener('click', enterBlendMode);
  document.getElementById('blendCount').addEventListener('change', e => {
    splitSegmentsEven(parseInt(e.target.value, 10));
    onStateChange();
  });
  document.getElementById('blendResplitBtn').addEventListener('click', () => {
    splitSegmentsEven(blendSegs().length);
    onStateChange();
  });

  /* ---- 画面融合校准 ---- */
  bindNum('calTarget', () => state.cal.target, v => { state.cal.target = v; }, 1);
  bindNum('calTolerance', () => state.cal.tolerance, v => { state.cal.tolerance = v; }, 1);

  /* ---- 拼接设备编辑 ---- */
  bindNum('bschU0', () => B()?.u0, v => { const g = B(); if (g) g.u0 = v; });
  bindNum('bschU1', () => B()?.u1, v => { const g = B(); if (g) g.u1 = v; });
  bindNum('bschOverlap', () => B()?.min_overlap, v => { const g = B(); if (g) g.min_overlap = v; });
  bindNum('bschClearance', () => B()?.clearance, v => { const g = B(); if (g) g.clearance = v; });
  bindNum('bschTrMin', () => B()?.scheme.tr_min, v => { const g = B(); if (g) g.scheme.tr_min = v; });
  bindNum('bschTrMax', () => B()?.scheme.tr_max, v => { const g = B(); if (g) g.scheme.tr_max = v; });
  bindNum('bschHShift', () => (B()?.scheme.h_shift ?? 0) * 100, v => { const g = B(); if (g) g.scheme.h_shift = v / 100; }, 0);
  bindNum('bschVShift', () => (B()?.scheme.v_shift ?? 0) * 100, v => { const g = B(); if (g) g.scheme.v_shift = v / 100; }, 0);
  bindNum('bschBodyW', () => B()?.scheme.body_w, v => { const g = B(); if (g) g.scheme.body_w = v; });
  bindNum('bschBodyD', () => B()?.scheme.body_d, v => { const g = B(); if (g) g.scheme.body_d = v; });
  bindNum('bschBodyH', () => B()?.scheme.body_h, v => { const g = B(); if (g) g.scheme.body_h = v; });
  bindNum('bschLensZ', () => B()?.lensZ, v => { const g = B(); if (g) g.lensZ = v; });
  document.getElementById('bschName').addEventListener('input', e => {
    const g = currentSeg();
    if (g) { g.scheme.name = e.target.value; renderBlendList(); scheduleCompute(); }
  });

  /* ---- 禁装区 ---- */
  const drawBtn = document.getElementById('drawBtn');
  drawBtn.addEventListener('click', () => {
    state.drawMode = !state.drawMode;
    drawBtn.classList.toggle('active', state.drawMode);
    topSvg.classList.toggle('drawing', state.drawMode);
  });
  document.getElementById('delObstacleBtn').addEventListener('click', deleteSelectedObstacle);
  window.addEventListener('keydown', e => {
    const tag = (e.target.tagName || '').toUpperCase();
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && state.selectedObstacleId) {
      deleteSelectedObstacle();
    } else if (e.key === 'Escape') {
      state.drawMode = false;
      state.selectedObstacleId = null;
      drawBtn.classList.remove('active');
      topSvg.classList.remove('drawing');
      onStateChange();
    }
  });
}

function deleteSelectedObstacle() {
  if (!state.selectedObstacleId) return;
  state.obstacles = state.obstacles.filter(o => o.id !== state.selectedObstacleId);
  state.selectedObstacleId = null;
  onStateChange();
}

/* ================= 拖拽交互 ================= */
function startDrag(e, info) {
  drag = info;
  e.stopPropagation();
  e.preventDefault();
}

function attachViewHandlers() {
  topSvg.addEventListener('pointerdown', e => {
    const p = svgWorld(topSvg, e);
    const W = state.room.width, D = state.room.depth;
    if (state.drawMode) {
      drag = { type: 'draw', x0: clamp(p.x, 0, W), y0: clamp(p.y, 0, D), x1: clamp(p.x, 0, W), y1: clamp(p.y, 0, D) };
      onStateChange();
      return;
    }
    if (state.mode === 'single') {
      state.point.x = clamp(p.x, 0, W);
      state.point.y = clamp(p.y, 0, D);
      drag = { type: 'point' };
    } else {
      // 拼接模式：空白处拖动当前选中设备
      const seg = currentSeg();
      if (seg) {
        seg.point = { x: clamp(p.x, 0, W), y: clamp(p.y, 0, D) };
        drag = { type: 'bpoint', idx: state.blend.selectedIdx };
      }
    }
    onStateChange();
  });

  sideSvg.addEventListener('pointerdown', e => {
    const p = svgWorld(sideSvg, e);
    const y = clamp(p.x, 0, state.room.depth);
    const z = clamp(state.room.height - p.y, 0, state.room.height);
    if (state.mode === 'single') {
      state.point.y = y;
      state.lensHeight = z;
      drag = { type: 'sidepoint' };
    } else {
      const seg = currentSeg();
      if (seg) {
        seg.point = seg.point || { x: segCenterX(seg), y };
        seg.point.y = y;
        seg.lensZ = z;
        drag = { type: 'sidebpoint', idx: state.blend.selectedIdx };
      }
    }
    onStateChange();
  });

  window.addEventListener('pointermove', e => {
    if (!drag) return;
    if (drag.type === 'sidepoint') {
      const p = svgWorld(sideSvg, e);
      state.point.y = clamp(p.x, 0, state.room.depth);
      state.lensHeight = clamp(state.room.height - p.y, 0, state.room.height);
    } else if (drag.type === 'sidebpoint') {
      const seg = blendSegs()[drag.idx];
      const p = svgWorld(sideSvg, e);
      if (seg) {
        seg.point = seg.point || { x: segCenterX(seg), y: 0 };
        seg.point.y = clamp(p.x, 0, state.room.depth);
        seg.lensZ = clamp(state.room.height - p.y, 0, state.room.height);
      }
    } else if (drag.type === 'strip0' || drag.type === 'strip1') {
      const seg = blendSegs()[drag.idx];
      const p = svgWorld(stripSvg, e);
      const u = xToU(p.x);
      const Sw = state.screen.width;
      if (!seg) return;
      if (drag.type === 'strip0') {
        const lo = drag.idx > 0 ? blendSegs()[drag.idx - 1].u0 + 0.15 : -Sw * 0.4;
        seg.u0 = clamp(u, lo, seg.u1 - 0.15);
      } else {
        const hi = drag.idx < blendSegs().length - 1 ? blendSegs()[drag.idx + 1].u1 - 0.15 : Sw * 1.4;
        seg.u1 = clamp(u, seg.u0 + 0.15, hi);
      }
    } else {
      const p = svgWorld(topSvg, e);
      const W = state.room.width, D = state.room.depth;
      if (drag.type === 'point') {
        state.point.x = clamp(p.x, 0, W);
        state.point.y = clamp(p.y, 0, D);
      } else if (drag.type === 'bpoint') {
        const seg = blendSegs()[drag.idx];
        if (seg) {
          seg.point = seg.point || { x: 0, y: 0 };
          seg.point.x = clamp(p.x, 0, W);
          seg.point.y = clamp(p.y, 0, D);
        }
      } else if (drag.type === 'screen') {
        state.screen.cx = clamp(p.x - drag.dx, state.screen.width / 2, W - state.screen.width / 2);
      } else if (drag.type === 'ob') {
        const ob = state.obstacles.find(o => o.id === drag.id);
        if (ob) {
          ob.x = clamp(p.x - drag.dx, 0, W - ob.w);
          ob.y = clamp(p.y - drag.dy, 0, D - ob.h);
        }
      } else if (drag.type === 'obresize') {
        const ob = state.obstacles.find(o => o.id === drag.id);
        if (ob) {
          ob.w = clamp(p.x - ob.x, 0.1, W - ob.x);
          ob.h = clamp(p.y - ob.y, 0.1, D - ob.y);
        }
      } else if (drag.type === 'draw') {
        drag.x1 = clamp(p.x, 0, W);
        drag.y1 = clamp(p.y, 0, D);
      }
    }
    onStateChange();
  });

  window.addEventListener('pointerup', () => {
    if (!drag) return;
    if (drag.type === 'draw') {
      const x = Math.min(drag.x0, drag.x1), y = Math.min(drag.y0, drag.y1);
      const w = Math.abs(drag.x1 - drag.x0), h = Math.abs(drag.y1 - drag.y0);
      if (w > 0.08 && h > 0.08) {
        const ob = { id: uid(), name: `禁装区${state.obstacles.length + 1}`, x, y, w, h };
        state.obstacles.push(ob);
        state.selectedObstacleId = ob.id;
      }
    }
    drag = null;
    onStateChange();
  });
}

/* ================= 渲染总入口 ================= */
function render() {
  sanitize();
  renderTop();
  renderSide();
  renderStrip();
  if (state.mode === 'single') {
    renderSchemeList();
  } else {
    renderBlendList();
  }
  renderObstacleList();
  if (state.mode === 'single') renderPointInfoSingle();
  else { renderPointInfoBlend(); renderCalPanel(); }
  syncInputs();
}

/* ================= 示例 ================= */
function applyState(data) {
  state.room = { ...data.room };
  state.screen = { ...data.screen };
  state.schemes = data.schemes.map(s => ({ ...s, id: uid() }));
  state.obstacles = data.obstacles.map(o => ({ ...o, id: uid() }));
  state.selectedSchemeId = state.schemes.length ? state.schemes[0].id : null;
  state.selectedObstacleId = null;
  state.blendTemplate = data.blend || null;
  state.blend.segments = [];
  state.blend.selectedIdx = 0;
  state.cal = { target: 150, tolerance: 10 };
  state.calBands = {};
  blendResult = null;
  calResult = null;
  result = null;
  resultById = {};
  const first = state.schemes[0];
  state.point = {
    x: state.screen.cx,
    y: first ? clamp((first.tr_min + first.tr_max) / 2 * state.screen.width, 0, state.room.depth) : state.room.depth / 2,
  };
  state.lensHeight = state.screen.bottom + state.screen.height / 2;

  if (data.blend) {
    enterBlendMode();   // 内部会触发首次计算
  } else {
    enterSingleMode();
  }
}

async function initExamples() {
  try {
    const res = await fetch('/api/examples');
    examples = await res.json();
  } catch (err) {
    examples = [];
  }
  const sel = document.getElementById('exampleSelect');
  sel.innerHTML = '<option value="">载入示例…</option>' +
    examples.map(e => `<option value="${esc(e.id)}">${esc(e.name)}</option>`).join('');
  sel.addEventListener('change', () => {
    const ex = examples.find(x => x.id === sel.value);
    if (ex) applyState(ex.data);
    sel.value = '';
  });
  if (examples.length) applyState(examples[0].data);
}

/* ================= 启动 ================= */
bindAllInputs();
attachViewHandlers();
applyModeChrome();
render();
initExamples();
