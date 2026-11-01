/*
 * Goggles & Windchimes account client. Shared by the site's account, commissions and
 * admin pages and by every web game served from gandw.io (load /assets/js/gw.js).
 *
 *   GW.me()                         -> {ok, user, games} | {ok:false, error:'signed_out'}
 *   GW.loadSave(game)               -> {ok, save: {data, rev, updated, summary} | null}
 *   GW.putSave(game, data, opts)    -> {ok, rev, updated} | {ok:false, error:'conflict', save}
 *        opts = {baseRev, summary, force}
 *   GW.accountUrl(next)             -> '/account/?next=...'  (send players here to sign in)
 *
 * The session lives in an HttpOnly cookie scoped to /api, so scripts never see it and it
 * is never sent anywhere but this API. Every call is same-origin; nothing leaves gandw.io.
 */
(function () {
  'use strict';

  var GW = {};

  GW.api = function (method, path, body) {
    var opt = { method: method, credentials: 'same-origin', headers: { 'x-gw-client': '1' } };
    if (body !== undefined) {
      opt.headers['content-type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    return fetch('/api' + path, opt).then(function (r) {
      var ct = r.headers.get('content-type') || '';
      if (ct.indexOf('json') === -1) {
        // e.g. the HTML 404 page: the API isn't deployed here (local dev without --api)
        return { ok: false, status: r.status, error: 'unavailable',
                 message: 'The account service isn’t available right now.' };
      }
      return r.json().then(function (data) {
        data.status = r.status;
        data.ok = r.ok && !data.error;
        return data;
      });
    }, function () {
      return { ok: false, status: 0, error: 'offline',
               message: 'Couldn’t reach gandw.io. Check your connection and try again.' };
    });
  };

  GW.me = function () { return GW.api('GET', '/me'); };
  GW.loadSave = function (game) { return GW.api('GET', '/games/' + game + '/save'); };
  GW.putSave = function (game, data, opts) {
    opts = opts || {};
    return GW.api('PUT', '/games/' + game + '/save', {
      data: data, base_rev: opts.baseRev == null ? null : opts.baseRev,
      summary: opts.summary || {}, force: !!opts.force
    });
  };
  GW.signOut = function () { return GW.api('POST', '/auth/logout', {}); };
  GW.accountUrl = function (next) {
    return '/account/' + (next ? '?next=' + encodeURIComponent(next) : '');
  };
  GW.hasRole = function (user, role) {
    return !!user && (user.roles.indexOf(role) !== -1 || user.roles.indexOf('admin') !== -1);
  };

  // ------------------------------------------------------------------ page helpers
  // Everything user-supplied goes in through textContent, never innerHTML.
  GW.$ = function (sel, root) { return (root || document).querySelector(sel); };
  GW.$$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  GW.el = function (tag, attrs) {
    var n = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'text') n.textContent = v;
      else if (k === 'class') n.className = v;
      else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null || c === false) continue;
      n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return n;
  };

  GW.show = function (node, on) {
    if (typeof node === 'string') node = GW.$(node);
    if (node) node.hidden = !on;
  };

  GW.say = function (node, text, kind) {
    if (typeof node === 'string') node = GW.$(node);
    if (!node) return;
    node.textContent = text || '';
    node.className = 'msg' + (kind ? ' msg--' + kind : '');
    node.hidden = !text;
  };

  GW.formData = function (form) {
    var out = {};
    GW.$$('input, textarea, select', form).forEach(function (f) {
      if (!f.name) return;
      out[f.name] = f.type === 'checkbox' ? f.checked : f.value;
    });
    return out;
  };

  // Disable a form's buttons while a request is in flight.
  GW.busy = function (form, on) {
    GW.$$('button', form).forEach(function (b) { b.disabled = on; });
  };

  GW.date = function (isoStr) {
    if (!isoStr) return '—';
    var d = new Date(isoStr);
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  };
  GW.when = function (isoStr) {
    if (!isoStr) return '—';
    var d = new Date(isoStr);
    return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric',
                                          hour: 'numeric', minute: '2-digit' });
  };

  // Only ever redirect to a path on this site.
  GW.safeNext = function () {
    var n = new URLSearchParams(location.search).get('next') || '';
    return /^\/(?!\/)[\w\-./?=&%#]*$/.test(n) ? n : '';
  };

  // A button that needs a second click to fire (instead of a blocking confirm() dialog).
  GW.confirmButton = function (label, confirmLabel, action, cls) {
    var armed = false, timer = null;
    var b = GW.el('button', { type: 'button', class: cls || 'btn btn--ghost btn--sm', text: label });
    b.addEventListener('click', function () {
      if (!armed) {
        armed = true; b.textContent = confirmLabel; b.classList.add('btn--danger');
        timer = setTimeout(function () { armed = false; b.textContent = label; b.classList.remove('btn--danger'); }, 4000);
        return;
      }
      clearTimeout(timer); armed = false; b.textContent = label; b.classList.remove('btn--danger');
      action(b);
    });
    return b;
  };

  // Plain-text paragraphs: blank lines split paragraphs; single newlines become <br>.
  GW.paragraphs = function (container, textValue) {
    container.textContent = '';
    (textValue || '').split(/\n{2,}/).forEach(function (para) {
      if (!para.trim()) return;
      var p = GW.el('p');
      para.split('\n').forEach(function (line, i) {
        if (i) p.appendChild(GW.el('br'));
        p.appendChild(document.createTextNode(line));
      });
      container.appendChild(p);
    });
  };

  window.GW = GW;
})();
