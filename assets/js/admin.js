/* /admin/ — commission reqs, accounts, and the update list. Needs gw.js. Admin role only. */
(function () {
  'use strict';
  var $ = GW.$, el = GW.el, say = GW.say, show = GW.show;
  var ME = null;
  var STATUS = { open: 'Open', earmarked: 'Earmarked', done: 'Done', closed: 'Closed' };

  function btn(label, fn, cls) {
    return el('button', { type: 'button', class: cls || 'btn btn--ghost btn--sm', text: label, onclick: fn });
  }

  // ------------------------------------------------------------------ tabs
  function tab(which) {
    ['reqs', 'users', 'subs'].forEach(function (t) {
      show('#p-' + t, t === which);
      $('#tab-' + t).setAttribute('aria-selected', t === which ? 'true' : 'false');
    });
    if (which === 'reqs') loadReqs();
    if (which === 'users') loadUsers();
    if (which === 'subs') loadSubs();
  }

  // ------------------------------------------------------------------ reqs
  function resetReqForm() {
    var f = $('#f-req');
    f.reset();
    f.elements.id.value = '';
    $('#req-submit').textContent = 'Post req';
    show('#req-cancel', false);
    $('#req-form-title').textContent = 'Post a new req';
  }

  function editReq(q) {
    var f = $('#f-req');
    ['id', 'title', 'summary', 'description', 'fee', 'due'].forEach(function (k) { f.elements[k].value = q[k] || ''; });
    $('#req-submit').textContent = 'Save changes';
    $('#req-form-title').textContent = 'Edit “' + q.title + '”';
    show('#req-cancel', true);
    f.scrollIntoView({ behavior: 'smooth', block: 'start' });
    f.elements.title.focus();
  }

  function setStatus(q, status, note) {
    GW.api('PATCH', '/admin/reqs/' + q.id, { status: status }).then(function (r) {
      say('#reqs-msg', r.ok ? note : r.message, r.ok ? 'ok' : 'err');
      loadReqs();
    });
  }

  function loadReqs() {
    GW.api('GET', '/admin/reqs').then(function (r) {
      var list = $('#admin-reqs');
      list.textContent = '';
      if (!r.ok) { say('#reqs-msg', r.message, 'err'); return; }
      r.reqs.forEach(function (q) {
        var actions = el('div', { class: 'row-actions' }, btn('Edit', function () { editReq(q); }));
        if (q.status === 'earmarked') {
          actions.append(btn('Mark done', function () { setStatus(q, 'done', 'Marked done.'); }));
          actions.append(GW.confirmButton('Clear earmark', 'Click again to clear', function () {
            setStatus(q, 'open', 'Earmark cleared; the req is open again.');
          }));
        }
        if (q.status === 'open') actions.append(btn('Close', function () { setStatus(q, 'closed', 'Closed. Artists no longer see it.'); }));
        if (q.status === 'done' || q.status === 'closed') actions.append(btn('Reopen', function () { setStatus(q, 'open', 'Reopened.'); }));
        actions.append(GW.confirmButton('Delete', 'Click again to delete', function () {
          GW.api('DELETE', '/admin/reqs/' + q.id).then(function (x) {
            say('#reqs-msg', x.ok ? 'Deleted.' : x.message, x.ok ? 'ok' : 'err'); loadReqs();
          });
        }));
        var who = q.earmarked_by ? 'Earmarked by ' + q.earmarked_by + ' on ' + GW.date(q.earmarked_at) : '';
        list.appendChild(el('li', { class: 'adminrow' },
          el('div', { class: 'adminrow__main' },
            el('strong', { text: q.title }),
            el('span', { class: 'pill pill--' + q.status, text: STATUS[q.status] }),
            el('div', { class: 'adminrow__meta',
                        text: [q.fee, q.due ? 'due ' + q.due : '', 'posted ' + GW.date(q.created), who]
                              .filter(Boolean).join(' · ') })),
          actions));
      });
      show('#admin-reqs-empty', !r.reqs.length);
    });
  }

  // ------------------------------------------------------------------ accounts
  function hasRole(u, r) { return u.roles.indexOf(r) !== -1; }

  function patchUser(u, body, note) {
    return GW.api('PATCH', '/admin/users/' + encodeURIComponent(u.username), body).then(function (r) {
      if (!r.ok) { say('#users-msg', r.message, 'err'); return r; }
      if (r.temp_password) showTemp(u.username, r.temp_password, 'New temporary password');
      else say('#users-msg', note, 'ok');
      loadUsers();
      return r;
    });
  }

  function toggleRole(u, role) {
    var roles = hasRole(u, role) ? u.roles.filter(function (x) { return x !== role; }) : u.roles.concat([role]);
    var note = (hasRole(u, role) ? 'Removed ' : 'Granted ') + role + (hasRole(u, role) ? ' from ' : ' to ') + u.username + '.';
    if (role === 'artist' && hasRole(u, 'artist') && u.holding) note += ' Their earmarked reqs are open again.';
    patchUser(u, { roles: roles }, note);
  }

  function showTemp(name, pw, label) {
    var box = $('#temp-box');
    $('#temp-label').textContent = label + ' for ' + name;
    $('#temp-pw').textContent = pw;
    show(box, true);
    say('#users-msg', '');
    box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function loadUsers() {
    GW.api('GET', '/admin/users').then(function (r) {
      var list = $('#admin-users');
      list.textContent = '';
      if (!r.ok) { say('#users-msg', r.message, 'err'); return; }
      $('#users-count').textContent = r.users.length + ' account' + (r.users.length === 1 ? '' : 's') +
        ', ' + r.users.filter(function (u) { return hasRole(u, 'artist'); }).length + ' artist(s)';
      var filter = ($('#users-filter').value || '').toLowerCase();
      var onlyArtists = $('#users-artists').checked;
      r.users.filter(function (u) {
        return (!filter || u.username.toLowerCase().indexOf(filter) !== -1) && (!onlyArtists || hasRole(u, 'artist'));
      }).forEach(function (u) {
        var self = ME && u.username === ME.username;
        var roles = el('span', { class: 'pillrow' });
        u.roles.forEach(function (x) { roles.appendChild(el('span', { class: 'pill pill--' + x, text: x })); });
        var actions = el('div', { class: 'row-actions' },
          btn(hasRole(u, 'artist') ? 'Remove artist' : 'Make artist', function () { toggleRole(u, 'artist'); }));
        if (!self) {
          actions.append(hasRole(u, 'admin')
            ? GW.confirmButton('Remove admin', 'Click again to confirm', function () { toggleRole(u, 'admin'); })
            : GW.confirmButton('Make admin', 'Click again to confirm', function () { toggleRole(u, 'admin'); }));
          actions.append(GW.confirmButton('Reset password', 'Click again to reset', function () {
            patchUser(u, { reset_password: true });
          }));
          actions.append(GW.confirmButton('Delete', 'Click again to delete', function () {
            GW.api('DELETE', '/admin/users/' + encodeURIComponent(u.username)).then(function (x) {
              say('#users-msg', x.ok ? 'Deleted ' + u.username + ' and their saves.' : x.message, x.ok ? 'ok' : 'err');
              loadUsers();
            });
          }));
        }
        var meta = ['joined ' + GW.date(u.created), 'last sign-in ' + GW.date(u.last_login)];
        if (u.holding) meta.push('holding ' + u.holding + ' req' + (u.holding === 1 ? '' : 's'));
        if (u.must_change_password) meta.push('temporary password');
        if (u.updates) meta.push('on update list');
        list.appendChild(el('li', { class: 'adminrow' },
          el('div', { class: 'adminrow__main' },
            el('strong', { text: u.username + (self ? ' (you)' : '') }), roles,
            el('div', { class: 'adminrow__meta', text: meta.join(' · ') })),
          actions));
      });
    });
  }

  // ------------------------------------------------------------------ update list
  function loadSubs() {
    GW.api('GET', '/admin/subscribers').then(function (r) {
      var list = $('#admin-subs');
      list.textContent = '';
      if (!r.ok) { say('#subs-msg', r.message, 'err'); return; }
      $('#subs-count').textContent = r.verified + ' confirmed, ' + (r.subscribers.length - r.verified) + ' waiting to confirm';
      r.subscribers.forEach(function (s) {
        list.appendChild(el('li', { class: 'adminrow' },
          el('div', { class: 'adminrow__main' },
            el('strong', { text: s.email }),
            el('span', { class: 'pill pill--' + (s.status === 'verified' ? 'open' : 'closed'), text: s.status }),
            el('div', { class: 'adminrow__meta', text: s.username + ' · since ' + GW.date(s.since) }))));
      });
      show('#admin-subs-empty', !r.subscribers.length);
      $('#subs-copy').onclick = function () {
        var txt = r.subscribers.filter(function (s) { return s.status === 'verified'; })
                   .map(function (s) { return s.email; }).join('\n');
        navigator.clipboard.writeText(txt).then(function () {
          say('#subs-msg', 'Copied ' + r.verified + ' confirmed address(es). Use BCC, and include a way to unsubscribe.', 'ok');
        }, function () { say('#subs-msg', 'Couldn’t copy. Select the list and copy it manually.', 'err'); });
      };
    });
  }

  // ------------------------------------------------------------------ init
  function init() {
    GW.me().then(function (me) {
      show('#a-loading', false);
      if (!me.ok || me.user.roles.indexOf('admin') === -1) {
        show('#a-denied', true);
        var a = $('#a-signin'); a.href = GW.accountUrl('/admin/');
        show(a, !me.ok);
        return;
      }
      ME = me.user;
      show('#a-panel', true);
      $('#a-who').textContent = ME.username;
      ['reqs', 'users', 'subs'].forEach(function (t) {
        $('#tab-' + t).addEventListener('click', function () { tab(t); });
      });
      tab('reqs');
    });

    $('#f-req').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      var id = d.id; delete d.id;
      GW.busy(f, true);
      (id ? GW.api('PATCH', '/admin/reqs/' + id, d) : GW.api('POST', '/admin/reqs', d)).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#req-msg', r.message, 'err'); return; }
        say('#req-msg', id ? 'Saved.' : 'Posted. Artists can see it now.', 'ok');
        resetReqForm(); loadReqs();
      });
    });
    $('#req-cancel').addEventListener('click', function () { resetReqForm(); say('#req-msg', ''); });

    $('#f-user').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      var roles = ['player'];
      if (d.artist) roles.push('artist');
      if (d.admin) roles.push('admin');
      GW.busy(f, true);
      GW.api('POST', '/admin/users', { username: d.username, roles: roles }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#users-msg', r.message, 'err'); return; }
        f.reset(); f.elements.artist.checked = true;
        showTemp(r.user.username, r.temp_password, 'Temporary password');
        loadUsers();
      });
    });
    $('#temp-hide').addEventListener('click', function () { show('#temp-box', false); $('#temp-pw').textContent = ''; });
    $('#temp-copy').addEventListener('click', function () {
      navigator.clipboard.writeText($('#temp-pw').textContent);
    });
    $('#users-filter').addEventListener('input', loadUsers);
    $('#users-artists').addEventListener('change', loadUsers);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
