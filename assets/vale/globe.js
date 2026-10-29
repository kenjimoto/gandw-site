/* Atlas of Vale — interactive globe for gandw.io/vale/atlas/.
   Runs under the site's strict CSP: no inline scripts, no inline style attributes
   (element.style via the DOM is fine), everything served from this domain. */
(function () {
  'use strict';
  var D = window.VALE;
  var root = document.getElementById('globe');
  if (!root || !D || !window.THREE) return;

  var stage = document.getElementById('stage');
  var box = document.getElementById('labels');
  var loadEl = document.getElementById('load');

  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (e) {
    loadEl.textContent = 'This atlas needs WebGL, which your browser has turned off.';
    return;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  stage.appendChild(renderer.domElement);
  renderer.domElement.setAttribute('aria-label', 'Interactive globe of Vale. Drag to turn, scroll or pinch to zoom.');
  renderer.domElement.setAttribute('role', 'img');

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
  var controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08; controls.enablePan = false;
  controls.minDistance = 1.18; controls.maxDistance = 6; controls.rotateSpeed = 0.5;

  // The globe sits inside a scrolling page, so the wheel only zooms once the reader has
  // clicked into it. Otherwise scrolling past would get captured.
  controls.enableZoom = false;
  renderer.domElement.addEventListener('pointerdown', function () { controls.enableZoom = true; root.classList.add('globe--active'); });
  root.addEventListener('mouseleave', function () { controls.enableZoom = false; root.classList.remove('globe--active'); });

  // Lat/lon to xyz, matching THREE.SphereGeometry UVs (u = lon/360 from 0 deg E).
  function ll2v(lat, lon, r) {
    var la = lat * Math.PI / 180, lo = lon * Math.PI / 180; r = r || 1;
    return new THREE.Vector3(-Math.cos(lo) * Math.cos(la) * r, Math.sin(la) * r, Math.sin(lo) * Math.cos(la) * r);
  }

  // --- stars
  (function () {
    var g = new THREE.BufferGeometry(), n = 2500, p = new Float32Array(n * 3);
    for (var i = 0; i < n; i++) {
      var v = new THREE.Vector3(Math.random() - .5, Math.random() - .5, Math.random() - .5).normalize();
      v.multiplyScalar(40 + Math.random() * 20); p.set([v.x, v.y, v.z], i * 3);
    }
    g.setAttribute('position', new THREE.BufferAttribute(p, 3));
    scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0xbfc8d8, size: 0.08, sizeAttenuation: true, transparent: true, opacity: .7 })));
  })();

  // --- globe
  var BASE = '/assets/vale/';
  var maxTex = renderer.capabilities.maxTextureSize;
  var big = maxTex >= 8192 && !/Mobi|Android/i.test(navigator.userAgent);
  var SRC = {
    terrain: big ? 'terrain_8k.jpg' : 'terrain_4k.jpg', biome: 'biome_4k.jpg',
    climate: 'climate_4k.jpg', art: big ? 'art_8k.jpg' : 'art_4k.jpg'
  };
  var loader = new THREE.TextureLoader();
  var tex = {};
  function getTex(k, cb) {
    if (tex[k]) return cb(tex[k]);
    loader.load(BASE + SRC[k], function (t) {
      t.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      t.encoding = THREE.sRGBEncoding; tex[k] = t; cb(t);
    });
  }
  renderer.outputEncoding = THREE.sRGBEncoding;
  var globeMat = new THREE.MeshLambertMaterial({ color: 0xffffff });
  var globe = new THREE.Mesh(new THREE.SphereGeometry(1, 192, 128), globeMat);
  scene.add(globe);
  scene.add(new THREE.AmbientLight(0xffffff, 0.78));
  var sun = new THREE.DirectionalLight(0xfff4e0, 0.42); camera.add(sun); sun.position.set(-1.5, 1.2, 1); scene.add(camera);

  scene.add(new THREE.Mesh(new THREE.SphereGeometry(1.06, 96, 64), new THREE.ShaderMaterial({
    transparent: true, side: THREE.BackSide, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: 'varying vec3 vN; void main(){ vN = normalize(normalMatrix*normal); gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }',
    fragmentShader: 'varying vec3 vN; void main(){ float i = pow(0.72 - dot(vN, vec3(0,0,1.)), 3.0); gl_FragColor = vec4(0.45,0.66,0.95,1.)*i*1.4; }'
  })));

  // --- graticule: 15 deg grid; equator, tropics (+/-22.5) and polar circles (+/-67.5) stronger
  var grid = new THREE.Group(); scene.add(grid);
  function lineOf(pts, mat) {
    var l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat);
    if (mat.isLineDashedMaterial) l.computeLineDistances();
    return l;
  }
  var thin = new THREE.LineBasicMaterial({ color: 0xe9e3d3, transparent: true, opacity: .13 });
  var strong = new THREE.LineBasicMaterial({ color: 0xd9a441, transparent: true, opacity: .55 });
  var dashed = new THREE.LineDashedMaterial({ color: 0xd9a441, transparent: true, opacity: .6, dashSize: .012, gapSize: .01 });
  var lat, lo, la, p;
  for (lat = -75; lat <= 75; lat += 15) { if (lat === 0) continue; p = []; for (lo = 0; lo <= 360; lo += 2) p.push(ll2v(lat, lo, 1.0015)); grid.add(lineOf(p, thin)); }
  for (lo = 0; lo < 360; lo += 15) { p = []; for (la = -90; la <= 90; la += 2) p.push(ll2v(la, lo, 1.0015)); grid.add(lineOf(p, thin)); }
  [[0, strong], [22.5, dashed], [-22.5, dashed], [67.5, dashed], [-67.5, dashed]].forEach(function (a) {
    var q = []; for (var x = 0; x <= 360; x += 1) q.push(ll2v(a[0], x, 1.002)); grid.add(lineOf(q, a[1]));
  });

  // --- Laputan storm track: great circle, inclination 63.7 deg, ascending node 336 deg E
  var lap = new THREE.Group(); lap.visible = false; scene.add(lap);
  (function () {
    var inc = 63.7 * Math.PI / 180, node = 336, core = [], up = [], dn = [];
    function latAt(x) { return Math.atan(Math.tan(inc) * Math.sin((x - node) * Math.PI / 180)) * 180 / Math.PI; }
    for (var x = 0; x <= 360; x += 1) {
      var l = latAt(x);
      core.push(ll2v(l, x, 1.003)); up.push(ll2v(Math.min(89, l + 7), x, 1.0025)); dn.push(ll2v(Math.max(-89, l - 7), x, 1.0025));
    }
    lap.add(lineOf(core, new THREE.LineBasicMaterial({ color: 0xff9d5c, transparent: true, opacity: .95 })));
    var edge = new THREE.LineDashedMaterial({ color: 0xff9d5c, transparent: true, opacity: .45, dashSize: .02, gapSize: .015 });
    lap.add(lineOf(up, edge)); lap.add(lineOf(dn, edge));
  })();

  // --- legend
  var LEG = {
    terrain: { t: 'Terrain', rows: [['#2e622c', 'Rainforest'], ['#42723a', 'Deciduous forest'], ['#546c50', 'Taiga'], ['#8a9e56', 'Grassland'], ['#b8a460', 'Savanna'], ['#d6b884', 'Desert'], ['#aa9268', 'Warm scrub'], ['#465a3a', 'Swamp'], ['#7a7a70', 'Boreal mountain'], ['#eef2f8', 'Ice']],
      p: 'Coastlines from the surveyed Ometia plate, with the newer islands of the Westerly and Easterly maps. The O’Pinne follows the world sheet.' },
    biome: { t: 'Biomes', rows: [['#28aa50', 'Deciduous rain forest'], ['#78c43c', 'Tropical rainforest'], ['#3cbeaa', 'Taiga'], ['#4682d2', 'Boreal mountain'], ['#c4d63c', 'Grassland'], ['#e87828', 'Savanna'], ['#d63428', 'Desert'], ['#de4696', 'Warm scrub land'], ['#8c3cc8', 'Swamp'], ['#ebf0fa', 'Ice wastes']],
      p: 'From the Ometia and O’Pinne biome maps. High-latitude tropics mark the Laputan storm band.' },
    climate: { t: 'Climate', rows: [['#1a783c', 'Tropical humid'], ['#96b43c', 'Tropical savanna'], ['#d6603c', 'Arid desert'], ['#e2a85a', 'Semi-arid scrub'], ['#5c9678', 'Humid subtropical'], ['#5caac8', 'Temperate oceanic'], ['#7878c8', 'Temperate continental'], ['#5a50a0', 'Subarctic'], ['#968c96', 'Highland / alpine'], ['#ecf0fa', 'Polar ice']],
      p: 'Zones worked out from biome and latitude. Oceans shade by surface warmth. Turn on the storm track to see what pulls the tropics poleward.' },
    art: { t: 'Map art', rows: [], p: 'The hand-drawn maps of Ometia and the O’Pinne, wrapped onto the sphere as drawn.' }
  };
  var legendEl = document.getElementById('legend');
  var layer = 'terrain';
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function drawLegend() {
    var L = LEG[layer];
    legendEl.textContent = '';
    legendEl.appendChild(el('div', 'globe__lt', L.t));
    if (L.rows.length) {
      var g = el('div', 'globe__lg');
      L.rows.forEach(function (r) { var s = el('span'), i = el('i'); i.style.background = r[0]; s.appendChild(i); s.appendChild(document.createTextNode(r[1])); g.appendChild(s); });
      legendEl.appendChild(g);
    }
    legendEl.appendChild(el('p', null, L.p));
    if (lap.visible) {
      var q = el('p'); q.appendChild(el('span', 'globe__ln'));
      q.appendChild(document.createTextNode('Laputa’s storm track, ±7° band. The city circles Vale three times a year.'));
      legendEl.appendChild(q);
    }
  }
  var segs = root.querySelectorAll('.globe__seg button');
  function setLayer(k) {
    layer = k;
    Array.prototype.forEach.call(segs, function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-l') === k); });
    getTex(k, function (t) { globeMat.map = t; globeMat.needsUpdate = true; loadEl.hidden = true; });
    drawLegend();
  }
  Array.prototype.forEach.call(segs, function (b) { b.addEventListener('click', function () { setLayer(b.getAttribute('data-l')); }); });
  var oNames = document.getElementById('o-names'), oGrid = document.getElementById('o-grid'),
      oLap = document.getElementById('o-laputa'), oSpin = document.getElementById('o-spin');
  oGrid.addEventListener('change', function () { grid.visible = oGrid.checked; });
  oLap.addEventListener('change', function () { lap.visible = oLap.checked; drawLegend(); });
  oNames.addEventListener('change', function () { box.hidden = !oNames.checked; });

  // --- labels
  var RANK = { region: 0, nation: 1, sea: 2, city: 3, keep: 4, water: 5, forest: 6, feature: 6, town: 7 };
  var items = [], regionDesc = {};
  D.regions.forEach(function (r) { regionDesc[r.n] = r.d; });
  D.regions.forEach(function (r) { items.push({ n: r.n, k: 'region', ll: r.ll, d: r.d, big: (r.n === 'Ometia' || r.n === "The O'Pinne Seas") }); });
  D.seas.forEach(function (s) { items.push({ n: s.n, k: 'sea', ll: s.ll }); });
  D.places.forEach(function (x) { items.push(x); });
  items.forEach(function (it) {
    var e = el('div', 'lb lb--' + it.k + (it.big ? ' lb--big' : ''), it.n);
    e.tabIndex = it.k === 'sea' ? -1 : 0;
    e.addEventListener('click', function (ev) { ev.stopPropagation(); select(it, true); });
    e.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') select(it, true); });
    box.appendChild(e); it.el = e; it.v = ll2v(it.ll[0], it.ll[1], 1.004); it.w = 0; it.h = 0;
  });
  function showAt(it, dist) {
    if (it.k === 'region') return it.big ? dist > 2.3 : (dist < 3.6 && dist > 1.32);
    if (it.k === 'nation') return dist < 3.6;
    if (it.k === 'sea') return dist < 3.2;
    if (it.k === 'city' || it.k === 'keep') return dist < 2.55;
    if (it.k === 'water') return dist < 2.1;
    return dist < 1.85;
  }
  var tmp = new THREE.Vector3(), camDir = new THREE.Vector3(), selected = null;
  function hide(it) { if (it.el.style.display !== 'none') it.el.style.display = 'none'; }
  function placeLabels() {
    if (!oNames.checked) return;
    var W = renderer.domElement.clientWidth, H = renderer.domElement.clientHeight, dist = camera.position.length();
    camDir.copy(camera.position).normalize();
    var vis = [];
    items.forEach(function (it) {
      var facing = it.v.clone().normalize().dot(camDir);
      if (facing < 0.18 + 0.4 / dist || !(showAt(it, dist) || it === selected)) return hide(it);
      tmp.copy(it.v).project(camera);
      var x = (tmp.x * .5 + .5) * W, y = (-tmp.y * .5 + .5) * H;
      if (x < -50 || x > W + 50 || y < -20 || y > H + 20) return hide(it);
      it.sx = x; it.sy = y; it.f = facing; vis.push(it);
    });
    vis.sort(function (a, b) { return (a === selected ? -1 : b === selected ? 1 : 0) || RANK[a.k] - RANK[b.k] || b.f - a.f; });
    var placed = [];
    vis.forEach(function (it) {
      if (it.el.style.display === 'none') it.el.style.display = '';
      if (!it.w) { it.w = it.el.offsetWidth; it.h = it.el.offsetHeight; }
      var centered = (it.k === 'region' || it.k === 'sea' || it.k === 'nation');
      var x0 = centered ? it.sx - it.w / 2 : it.sx - 4, y0 = it.sy - it.h / 2;
      var r = [x0 - 3, y0 - 2, x0 + it.w + 3, y0 + it.h + 2];
      if (it !== selected && placed.some(function (q) { return r[0] < q[2] && r[2] > q[0] && r[1] < q[3] && r[3] > q[1]; })) return hide(it);
      placed.push(r);
      it.el.style.opacity = Math.min(1, (it.f - 0.18 - 0.4 / dist) * 6).toFixed(2);
      it.el.style.transform = 'translate(' + x0.toFixed(1) + 'px,' + y0.toFixed(1) + 'px)';
    });
  }

  // --- selection / info card
  var info = document.getElementById('info'), body = document.getElementById('infobody');
  var KIND = { city: 'City', keep: 'Keep / stronghold', town: 'Town / settlement', water: 'Water', forest: 'Forest', feature: 'Landmark', nation: 'Nation', region: 'Realm', sea: 'Sea' };
  function fmtLL(ll) { return Math.abs(ll[0]).toFixed(1) + '° ' + (ll[0] >= 0 ? 'N' : 'S') + ', ' + ll[1].toFixed(1) + '° E'; }
  function zoneOf(a) { a = Math.abs(a); return a >= 67.5 ? 'Polar (beyond the polar circle)' : a >= 45 ? 'High temperate' : a > 22.5 ? 'Temperate' : 'Tropical (within ±22.5°)'; }
  function select(it, fly) {
    if (selected) selected.el.classList.remove('lb--sel');
    selected = it; it.el.classList.add('lb--sel');
    var d = it.d || (it.r ? regionDesc[it.r] : '') || '';
    body.textContent = '';
    body.appendChild(el('div', 'globe__meta', (KIND[it.k] || '') + (it.r && it.k !== 'region' ? ' · ' + it.r : '')));
    body.appendChild(el('h3', null, it.n));
    if (d) {
      var para = el('p');
      if (it.r && !it.d && it.k !== 'nation') para.appendChild(el('span', 'globe__dim', it.r + ': '));
      para.appendChild(document.createTextNode(d));
      body.appendChild(para);
    }
    var dl = el('dl');
    [['Position', fmtLL(it.ll)], ['Zone', zoneOf(it.ll[0])], it.src ? ['Source', it.src] : null].forEach(function (row) {
      if (!row) return; dl.appendChild(el('dt', null, row[0])); dl.appendChild(el('dd', null, row[1]));
    });
    body.appendChild(dl);
    info.hidden = false;
    if (fly) flyTo(it.ll);
  }
  document.getElementById('close').addEventListener('click', function () {
    info.hidden = true; if (selected) { selected.el.classList.remove('lb--sel'); selected = null; }
  });

  var flying = null;
  function flyTo(ll) {
    var from = camera.position.clone(), dist = Math.min(from.length(), 2.0);
    flying = { from: from, to: ll2v(ll[0], ll[1], 1).normalize().multiplyScalar(dist), t: 0 };
  }

  // --- search
  var q = document.getElementById('q'), hits = document.getElementById('hits');
  function norm(s) { return s.toLowerCase().normalize('NFD').replace(/[̀-ͯ'’–\-\s]/g, ''); }
  q.addEventListener('input', function () {
    var s = norm(q.value); hits.textContent = '';
    if (s.length < 2) return;
    items.filter(function (it) { return norm(it.n).indexOf(s) >= 0; })
      .sort(function (a, b) { return norm(a.n).indexOf(s) - norm(b.n).indexOf(s); })
      .slice(0, 12).forEach(function (it) {
        var li = el('li'), b = el('button');
        b.type = 'button';
        b.appendChild(el('span', null, it.n)); b.appendChild(el('small', null, it.r || KIND[it.k] || ''));
        b.addEventListener('click', function () { select(it, true); hits.textContent = ''; q.value = it.n; });
        li.appendChild(b); hits.appendChild(li);
      });
  });

  // --- loop
  function resize() {
    var w = stage.clientWidth, h = stage.clientHeight;
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize); resize();
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  controls.addEventListener('start', function () { flying = null; });
  camera.position.copy(ll2v(18, 262, 1).multiplyScalar(camera.aspect < 0.8 ? 4.8 : 3.1));

  // Only animate while the globe is on screen.
  var onScreen = true, scheduled = false;
  function schedule() { if (!scheduled) { scheduled = true; requestAnimationFrame(loop); } }
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { onScreen = es[0].isIntersecting; if (onScreen) schedule(); }).observe(root);
  }
  function loop() {
    scheduled = false;
    frame();
    if (onScreen) schedule();
  }
  function frame() {
    if (flying) {
      flying.t = Math.min(1, flying.t + (reduce ? 1 : 0.035));
      var e = flying.t < .5 ? 2 * flying.t * flying.t : 1 - Math.pow(-2 * flying.t + 2, 2) / 2;
      var a = flying.from.clone().normalize(), b = flying.to.clone().normalize();
      var len = flying.from.length() * (1 - e) + flying.to.length() * e;
      camera.position.copy(a.lerp(b, e).normalize().multiplyScalar(len));
      if (flying.t >= 1) flying = null;
    }
    if (oSpin.checked && !flying) {
      var s = new THREE.Spherical().setFromVector3(camera.position); s.theta += 0.0015; camera.position.setFromSpherical(s);
    }
    controls.rotateSpeed = 0.25 + 0.35 * Math.min(1, (camera.position.length() - 1) / 2);
    controls.update();
    renderer.render(scene, camera);
    placeLabels();
  }
  setLayer('terrain');
  schedule();
})();
