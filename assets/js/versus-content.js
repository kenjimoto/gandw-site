/* /admin/versus/ — upload, check, stage and publish VERSUS content (content framework step 3).
 *
 * Needs gw.js and the game's own workbook checker, /versus/content/workbook-check.js
 * (window.VersusWorkbook: the same rules the game's build runs). The built-in content, its
 * fingerprint (base), the core version and the lists the checks use come from
 * /versus/content/workbook.json, so this page always checks against the game that is live.
 *
 * Reads .xlsx itself (a zip of XML: unzipped with the browser's DecompressionStream) or one
 * CSV per tab. No libraries: the site's CSP is 'self'. Author or admin role only.
 */
(function () {
  'use strict';
  var $ = GW.$, el = GW.el, say = GW.say, show = GW.show;
  var WB = window.VersusWorkbook;
  var GAME = null;          // {base, core, refs, content} from /versus/content/workbook.json
  var STATE = { live: null, staged: null, versions: [] };
  var CHECKED = null;       // {content, source} after a clean check

  function btn(label, fn, cls) {
    return el('button', { type: 'button', class: cls || 'btn btn--ghost btn--sm', text: label, onclick: fn });
  }
  function when(sec) { return sec ? GW.when(new Date(sec * 1000).toISOString()) : '—'; }

  // ------------------------------------------------------------------ zip (read and write)
  function u16(b, o) { return b[o] | (b[o + 1] << 8); }
  function u32(b, o) { return (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0; }

  /** A zip's files → Promise<{name: Uint8Array}> (stored or deflated entries). */
  function unzip(buf) {
    var b = new Uint8Array(buf), eocd = -1;
    for (var i = b.length - 22; i >= Math.max(0, b.length - 65557); i--) if (u32(b, i) === 0x06054b50) { eocd = i; break; }
    if (eocd < 0) return Promise.reject(new Error('That file isn’t an .xlsx (no zip directory found).'));
    var n = u16(b, eocd + 10), off = u32(b, eocd + 16), jobs = [], dec = new TextDecoder();
    for (var k = 0; k < n; k++) {
      if (u32(b, off) !== 0x02014b50) return Promise.reject(new Error('The .xlsx file looks damaged.'));
      var method = u16(b, off + 10), csize = u32(b, off + 20), nlen = u16(b, off + 28), xlen = u16(b, off + 30), clen = u16(b, off + 32);
      var local = u32(b, off + 42), name = dec.decode(b.subarray(off + 46, off + 46 + nlen));
      var start = local + 30 + u16(b, local + 26) + u16(b, local + 28);
      jobs.push(inflate(name, method, b.subarray(start, start + csize)));
      off += 46 + nlen + xlen + clen;
    }
    return Promise.all(jobs).then(function (pairs) { var o = {}; pairs.forEach(function (p) { o[p[0]] = p[1]; }); return o; });
  }
  function inflate(name, method, data) {
    if (method === 0) return Promise.resolve([name, data]);
    if (method !== 8) return Promise.reject(new Error('Unsupported compression in ' + name));
    if (typeof DecompressionStream === 'undefined') return Promise.reject(new Error('This browser can’t unzip .xlsx files. Use a current Chrome, Edge, Firefox or Safari, or upload CSV files.'));
    var stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return new Response(stream).arrayBuffer().then(function (ab) { return [name, new Uint8Array(ab)]; });
  }

  var CRC = (function () { var t = [], c; for (var n = 0; n < 256; n++) { c = n; for (var k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  function crc32(b) { var c = 0xFFFFFFFF; for (var i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; }
  /** {name: text} → a zip Blob (stored, not compressed: these are small). */
  function zip(files) {
    var enc = new TextEncoder(), parts = [], dir = [], off = 0, names = Object.keys(files);
    function le(n, bytes) { var a = []; for (var i = 0; i < bytes; i++) a.push((n >>> (8 * i)) & 0xFF); return a; }
    names.forEach(function (name) {
      var nb = enc.encode(name), data = enc.encode(files[name]), crc = crc32(data);
      var head = [].concat(le(0x04034b50, 4), le(20, 2), le(0x0800, 2), le(0, 2), le(0, 4), le(crc, 4), le(data.length, 4), le(data.length, 4), le(nb.length, 2), le(0, 2));
      parts.push(new Uint8Array(head), nb, data);
      dir.push(new Uint8Array([].concat(le(0x02014b50, 4), le(20, 2), le(20, 2), le(0x0800, 2), le(0, 2), le(0, 4), le(crc, 4), le(data.length, 4), le(data.length, 4),
        le(nb.length, 2), le(0, 2), le(0, 2), le(0, 2), le(0, 2), le(0, 4), le(off, 4))), nb);
      off += head.length + nb.length + data.length;
    });
    var dsize = dir.reduce(function (s, x) { return s + x.length; }, 0);
    var end = new Uint8Array([].concat(le(0x06054b50, 4), le(0, 2), le(0, 2), le(names.length, 2), le(names.length, 2), le(dsize, 4), le(off, 4), le(0, 2)));
    return new Blob(parts.concat(dir, [end]), { type: 'application/zip' });
  }
  function download(blob, name) {
    var a = el('a', { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
  }
  function workbookZip(content, name) {
    var T = WB.formatWorkbook(content), files = {};
    Object.keys(T).forEach(function (tab) { files[WB.tabFile(tab)] = WB.toCsv(T[tab]); });
    download(zip(files), name);
  }

  // ------------------------------------------------------------------ reading a workbook
  function colIndex(ref) { var m = /^([A-Z]+)/.exec(ref), n = 0; for (var i = 0; i < m[1].length; i++) n = n * 26 + m[1].charCodeAt(i) - 64; return n - 1; }
  function xml(bytes) { return new DOMParser().parseFromString(new TextDecoder().decode(bytes), 'application/xml'); }
  function kids(node, tag) { return Array.prototype.filter.call(node.getElementsByTagName('*'), function (n) { return n.localName === tag; }); }
  function textOf(node) { return kids(node, 't').map(function (t) { return t.textContent; }).join(''); }
  /** A number as a sheet stores it ("22", "2.5", "1E-3") → how a person typed it. */
  function num(v) { var n = Number(v); return Number.isFinite(n) ? String(Math.round(n * 1e9) / 1e9) : v; }

  /** .xlsx bytes → {tab: rows[][]} for the workbook's tabs (Read me and Lists are skipped). */
  function readXlsx(buf) {
    return unzip(buf).then(function (f) {
      if (!f['xl/workbook.xml']) throw new Error('That .xlsx has no workbook inside.');
      var shared = f['xl/sharedStrings.xml'] ? kids(xml(f['xl/sharedStrings.xml']), 'si').map(textOf) : [];
      var rels = {};
      kids(xml(f['xl/_rels/workbook.xml.rels']), 'Relationship').forEach(function (r) {
        var t = r.getAttribute('Target'); rels[r.getAttribute('Id')] = t.charAt(0) === '/' ? t.slice(1) : 'xl/' + t;
      });
      var out = {};
      kids(xml(f['xl/workbook.xml']), 'sheet').forEach(function (sh) {
        var name = sh.getAttribute('name');
        if (!WB.TABS[name]) return;
        var rid = sh.getAttribute('r:id') || sh.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id');
        var doc = f[rels[rid]]; if (!doc) return;
        var rows = [];
        kids(xml(doc), 'row').forEach(function (row) {
          var r = Number(row.getAttribute('r')) - 1, line = [];
          kids(row, 'c').forEach(function (c) {
            var t = c.getAttribute('t'), v = kids(c, 'v')[0], val = '';
            if (t === 's') val = shared[Number(v && v.textContent)] || '';
            else if (t === 'inlineStr') val = textOf(c);
            else if (t === 'b') val = v && v.textContent === '1' ? 'TRUE' : 'FALSE';
            else if (v) val = t === 'str' || t === 'e' ? v.textContent : num(v.textContent);
            line[colIndex(c.getAttribute('r'))] = val;
          });
          for (var i = 0; i < line.length; i++) if (line[i] === undefined) line[i] = '';
          rows[r] = line;
        });
        for (var i = 0; i < rows.length; i++) if (!rows[i]) rows[i] = [];
        out[name] = rows;
      });
      return out;
    });
  }

  /** The chosen files → {tab: rows} (one .xlsx, or CSVs named after their tabs). */
  function readFiles(files) {
    files = Array.prototype.slice.call(files);
    var x = files.filter(function (f) { return /\.xlsx$/i.test(f.name); });
    if (x.length > 1) return Promise.reject(new Error('Choose one .xlsx file (or the CSV files).'));
    if (x.length) return x[0].arrayBuffer().then(readXlsx);
    var byFile = {}; Object.keys(WB.TABS).forEach(function (t) { byFile[WB.tabFile(t)] = t; });
    var unknown = files.filter(function (f) { return !byFile[f.name.toLowerCase()]; }).map(function (f) { return f.name; });
    if (unknown.length) return Promise.reject(new Error('These files aren’t workbook tabs: ' + unknown.join(', ') + '. Expected names like ' + Object.keys(byFile).slice(0, 3).join(', ') + '.'));
    return Promise.all(files.map(function (f) { return f.text().then(function (t) { return [byFile[f.name.toLowerCase()], WB.parseCsv(t)]; }); }))
      .then(function (pairs) {
        // tabs not uploaded keep the game's own rows, so one CSV can be changed at a time
        var T = WB.formatWorkbook(GAME.content), out = {};
        Object.keys(WB.TABS).forEach(function (t) { out[t] = T[t]; });
        pairs.forEach(function (p) { out[p[0]] = p[1]; });
        return out;
      });
  }

  // ------------------------------------------------------------------ comparing content
  var PARTS = ['quests', 'npcs', 'items', 'bosses', 'lootTables', 'enemies', 'schedules'];
  var LABEL = { quests: 'quests', npcs: 'quest-givers', items: 'items', bosses: 'bosses', lootTables: 'loot tables', enemies: 'enemies', schedules: 'schedules' };
  function keyed(part, v) {
    var o = {};
    if (Array.isArray(v)) v.forEach(function (x) { o[x.id] = x; }); else Object.keys(v || {}).forEach(function (k) { o[k] = v[k]; });
    return o;
  }
  /** What b changes from a: [{part, added[], changed[], removed[]}] */
  function diff(a, b) {
    return PARTS.map(function (p) {
      var A = keyed(p, a && a[p]), B = keyed(p, b && b[p]), d = { part: p, added: [], changed: [], removed: [] };
      Object.keys(B).forEach(function (k) { if (!(k in A)) d.added.push(k); else if (JSON.stringify(A[k]) !== JSON.stringify(B[k])) d.changed.push(k); });
      Object.keys(A).forEach(function (k) { if (!(k in B)) d.removed.push(k); });
      return d;
    }).filter(function (d) { return d.added.length || d.changed.length || d.removed.length; });
  }
  function diffList(title, d) {
    var box = el('div', null, el('p', { class: 'panel__dek', text: title }));
    if (!d.length) { box.appendChild(el('p', { class: 'panel__dek', text: 'No changes.' })); return box; }
    var ul = el('ul', { class: 'changes' });
    d.forEach(function (x) {
      var bits = [];
      if (x.added.length) bits.push('adds ' + x.added.join(', '));
      if (x.changed.length) bits.push('changes ' + x.changed.join(', '));
      if (x.removed.length) bits.push('removes ' + x.removed.join(', '));
      ul.appendChild(el('li', null, el('strong', { text: LABEL[x.part] + ': ' }), bits.join('; ')));
    });
    box.appendChild(ul);
    return box;
  }

  // ------------------------------------------------------------------ checking
  function problemTable(list, kind) {
    var t = el('table', { class: 'probs' + (kind === 'err' ? ' probs--err' : '') },
      el('thead', null, el('tr', null, el('th', { text: 'Tab' }), el('th', { text: 'Row' }), el('th', { text: 'Column' }), el('th', { text: 'Problem' }))));
    var tb = el('tbody');
    list.slice(0, 200).forEach(function (p) {
      tb.appendChild(el('tr', null, el('td', { text: p.tab }), el('td', { text: String(p.row) }), el('td', { text: p.column || '' }), el('td', { text: p.message })));
    });
    t.appendChild(tb);
    return t;
  }

  function check(tables, source) {
    var r = WB.parseWorkbook(tables, GAME.refs);
    var box = $('#c-problems'); box.textContent = '';
    $('#c-diff').textContent = '';
    show('#c-result', true); show('#c-stage', false); say('#c-stage-msg', '');
    if (r.errors.length) {
      $('#c-result-title').textContent = r.errors.length + ' problem' + (r.errors.length > 1 ? 's' : '') + ' to fix';
      box.appendChild(el('p', { class: 'panel__dek', text: 'Nothing has been sent. Fix these in the workbook and check it again.' }));
      box.appendChild(problemTable(r.errors, 'err'));
      if (r.errors.length > 200) box.appendChild(el('p', { class: 'panel__dek', text: '…and ' + (r.errors.length - 200) + ' more.' }));
      CHECKED = null;
      return;
    }
    $('#c-result-title').textContent = 'The workbook checks out';
    if (r.warnings.length) {
      box.appendChild(el('p', { class: 'panel__dek', text: r.warnings.length + ' note' + (r.warnings.length > 1 ? 's' : '') + ' (these don’t stop it):' }));
      box.appendChild(problemTable(r.warnings, 'warn'));
    }
    var c = r.content, liveV = STATE.versions.find(function (v) { return v.version === STATE.live; });
    var d = $('#c-diff');
    d.appendChild(diffList('Compared with the game’s own content:', diff(GAME.content, c)));
    var gone = diff(GAME.content, c).filter(function (x) { return x.removed.length; });
    if (gone.length) d.appendChild(el('p', { class: 'msg msg--err', text: 'This removes things the game itself has. That’s fine if you meant it; saves that hold them keep working.' }));
    if (liveV) {
      GW.api('GET', '/admin/versus/content/' + liveV.version).then(function (full) {
        if (full.ok) d.appendChild(diffList('Compared with what’s published now (' + liveV.version + '):', diff(full.content, c)));
      });
    }
    CHECKED = { content: c, source: source };
    show('#c-stage', true);
  }

  // ------------------------------------------------------------------ status and versions
  function load() {
    return GW.api('GET', '/admin/versus/content').then(function (r) {
      if (!r.ok) { say('#c-versions-msg', r.message, 'err'); return; }
      STATE = r;
      var list = $('#c-versions'); list.textContent = '';
      r.versions.forEach(function (v) {
        var pills = el('span', { class: 'pillrow' });
        if (v.version === r.live) pills.appendChild(el('span', { class: 'pill pill--live', text: 'published' }));
        if (v.version === r.staged) pills.appendChild(el('span', { class: 'pill pill--staged', text: 'staged for you' }));
        if (v.base !== GAME.base) pills.appendChild(el('span', { class: 'pill pill--closed', text: 'for an older game' }));
        var counts = PARTS.filter(function (p) { return v.counts[p]; }).map(function (p) { return v.counts[p] + ' ' + LABEL[p]; }).join(', ');
        var actions = el('div', { class: 'row-actions' },
          btn('Download', function () { GW.api('GET', '/admin/versus/content/' + v.version).then(function (f) { if (f.ok) workbookZip(f.content, 'versus-workbook-' + v.version + '.zip'); }); }));
        if (v.version !== r.staged) actions.appendChild(btn('Stage', function () { act('POST', '/admin/versus/content/' + v.version + '/stage', v.version + ' is staged: open the game to play it. Only you see it.'); }));
        if (v.version !== r.live) actions.appendChild(GW.confirmButton(r.live && v.n < Number(r.live.slice(1)) ? 'Roll back to this' : 'Publish',
          'Click again: everyone gets it', function () { act('POST', '/admin/versus/content/' + v.version + '/publish', v.version + ' is published. Players get it the next time they open the game.'); }, 'btn btn--sm'));
        list.appendChild(el('li', { class: 'adminrow' },
          el('div', { class: 'adminrow__main' }, el('strong', { text: v.version }), pills, v.note ? el('span', { text: v.note }) : null,
            el('div', { class: 'adminrow__meta', text: 'Uploaded by ' + v.by + ', ' + when(v.at) + (v.published_at ? ' · last published ' + when(v.published_at) + ' by ' + v.published_by : '') + (counts ? ' · ' + counts : '') })),
          actions));
      });
      show('#c-versions-empty', !r.versions.length);
      show('#c-unstage', !!r.staged);
      var st = $('#c-status'); st.textContent = '';
      var liveV = r.versions.find(function (v) { return v.version === r.live; });
      st.appendChild(el('li', { text: r.live ? 'Published: ' + r.live + (liveV && liveV.base !== GAME.base ? ' — but it was made for an older version of the game, so players get the game’s own content until you publish again.' : '.') : 'Published: nothing. Players get the game’s own content.' }));
      st.appendChild(el('li', { text: r.staged ? 'You’re playing ' + r.staged + ' (staged; only you see it).' : 'You see what everyone sees.' }));
      st.appendChild(el('li', { text: 'The game: core ' + GAME.core + ', workbook ' + GAME.base + '.' }));
    });
  }
  function act(method, path, ok) {
    return GW.api(method, path).then(function (r) {
      say('#c-versions-msg', r.ok ? ok : r.message, r.ok ? 'ok' : 'err');
      return load();
    });
  }

  // ------------------------------------------------------------------ init
  function init() {
    if (!WB) { show('#c-loading', false); say('#c-status-msg', 'The game’s workbook checker didn’t load (/versus/content/workbook-check.js). Is the game deployed?', 'err'); show('#c-panel', true); return; }
    GW.me().then(function (me) {
      show('#c-loading', false);
      if (!me.ok || !GW.hasRole(me.user, 'author')) {
        show('#c-denied', true);
        var a = $('#c-signin'); a.href = GW.accountUrl('/admin/versus/'); show(a, !me.ok);
        return;
      }
      $('#c-who').textContent = me.user.username;
      show('#c-panel', true);
      fetch('/versus/content/workbook.json', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (g) {
        GAME = g; return load();
      }, function () { say('#c-status-msg', 'Couldn’t load the game’s content (/versus/content/workbook.json).', 'err'); });
    });

    $('#c-upload').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, files = f.elements.file.files;
      if (!files.length || !GAME) return;
      GW.busy(f, true); say('#c-check-msg', 'Reading…', 'info');
      readFiles(files).then(function (tables) {
        GW.busy(f, false); say('#c-check-msg', '');
        check(tables, Array.prototype.map.call(files, function (x) { return x.name; }).join(', '));
      }, function (err) { GW.busy(f, false); say('#c-check-msg', err.message, 'err'); });
    });

    $('#c-stage').addEventListener('submit', function (e) {
      e.preventDefault();
      if (!CHECKED) return;
      var f = e.target;
      GW.busy(f, true);
      GW.api('POST', '/admin/versus/content', { content: CHECKED.content, base: GAME.base, core: GAME.core,
        note: f.elements.note.value || ('from ' + CHECKED.source) }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#c-stage-msg', r.message, 'err'); return; }
        say('#c-stage-msg', r.version + ' is staged. Open the game at /versus/ to play it; only you see it. Publish it from the list below when you’re happy.', 'ok');
        show('#c-stage', false); f.reset(); CHECKED = null;
        load();
      });
    });
    $('#c-dl-game').addEventListener('click', function () { if (GAME) workbookZip(GAME.content, 'versus-workbook-game-' + GAME.base + '.zip'); });
    $('#c-unstage').addEventListener('click', function () { act('DELETE', '/admin/versus/stage', 'You see what everyone sees again.'); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
