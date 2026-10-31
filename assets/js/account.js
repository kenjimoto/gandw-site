/* /account/ — sign in, create an account, and manage it. Needs gw.js. */
(function () {
  'use strict';
  var $ = GW.$, el = GW.el, say = GW.say, show = GW.show;
  var GAME_NAMES = { versus: { name: 'VERSUS', href: '/versus/' } };

  function goNext() {
    var n = GW.safeNext();
    if (n) { location.href = n; return true; }
    return false;
  }

  // ------------------------------------------------------------------ signed out
  function tab(which) {
    ['login', 'register'].forEach(function (t) {
      var on = t === which;
      show('#f-' + t, on);
      $('#tab-' + t).setAttribute('aria-selected', on ? 'true' : 'false');
    });
    show('#f-help', false);
  }

  function signedOut() {
    show('#acct-loading', false);
    show('#acct-in', false);
    show('#acct-out', true);
    tab(location.hash === '#create' ? 'register' : 'login');
    if (GW.safeNext().indexOf('/versus') === 0) {
      say('#out-msg', 'Sign in or create a free account to keep your VERSUS save in the cloud.', 'info');
    }
  }

  // ------------------------------------------------------------------ signed in
  function render(data) {
    var u = data.user;
    show('#acct-loading', false);
    show('#acct-out', false);
    show('#acct-in', true);
    $('#me-name').textContent = u.username;
    $('#me-since').textContent = GW.date(u.created);

    var roles = $('#me-roles');
    roles.textContent = '';
    u.roles.forEach(function (r) { roles.appendChild(el('span', { class: 'pill pill--' + r, text: r })); });

    var links = $('#me-links');
    links.textContent = '';
    if (GW.hasRole(u, 'artist')) links.appendChild(el('a', { class: 'btn btn--ghost btn--sm', href: '/commissions/', text: 'Commission tracker' }));
    if (u.roles.indexOf('admin') !== -1) links.appendChild(el('a', { class: 'btn btn--ghost btn--sm', href: '/admin/', text: 'Admin' }));

    show('#must-change', u.must_change_password);

    // games
    var list = $('#games');
    list.textContent = '';
    (data.games || []).forEach(function (g) {
      var meta = GAME_NAMES[g.game] || { name: g.game, href: '/' };
      var s = g.summary || {};
      var bits = [];
      if (s.house != null) bits.push(s.house + '/6 in the House');
      if (s.wins != null) bits.push(s.wins + ' wins');
      if (s.losses != null) bits.push(s.losses + ' losses');
      if (s.day != null) bits.push('day ' + s.day);
      list.appendChild(el('li', { class: 'gamerow' },
        el('a', { href: meta.href, class: 'gamerow__name', text: meta.name }),
        el('span', { class: 'gamerow__meta', text: bits.join(' · ') || 'Saved' }),
        el('span', { class: 'gamerow__when', text: 'Cloud save ' + GW.when(g.updated) })));
    });
    show('#games-empty', !(data.games || []).length);

    // updates
    var up = u.updates;
    $('#up-on').checked = up.opted_in;
    $('#up-email').value = '';
    $('#up-email').placeholder = up.email || 'you@example.com';
    show('#up-email-row', up.opted_in);
    var st = $('#up-status');
    if (!up.opted_in) say(st, 'You’re not on the update list. No email address is stored.', 'info');
    else if (up.verified) say(st, 'Confirmed: updates go to ' + up.email + '.', 'ok');
    else say(st, 'Waiting for you to confirm ' + up.email + '. Check your inbox for a link.', 'info');
    show('#up-resend', up.opted_in && !up.verified);
  }

  function refresh() {
    return GW.me().then(function (r) {
      if (r.ok) { render(r); return r; }
      if (r.error === 'signed_out') { signedOut(); return r; }
      show('#acct-loading', false);
      say('#acct-error', r.message, 'err');
      return r;
    });
  }

  function verificationNote(v) {
    if (v === 'sent') return ' We’ve emailed you a link to confirm your address.';
    if (v === 'pending') return ' We couldn’t send the confirmation email just now; you can resend it from this page later.';
    return '';
  }

  // ------------------------------------------------------------------ wiring
  function init() {
    $('#tab-login').addEventListener('click', function () { tab('login'); });
    $('#tab-register').addEventListener('click', function () { tab('register'); });

    $('#show-help').addEventListener('click', function () {
      show('#f-login', false); show('#f-help', true); $('#help-username').focus();
    });
    $('#hide-help').addEventListener('click', function () { tab('login'); });

    $('#reg-updates').addEventListener('change', function (e) {
      show('#reg-email-row', e.target.checked);
      $('#reg-email').required = e.target.checked;
    });
    $('#up-on').addEventListener('change', function (e) {
      show('#up-email-row', e.target.checked);
    });

    $('#f-login').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      GW.busy(f, true); say('#login-msg', 'Signing in…', 'info');
      GW.api('POST', '/auth/login', { username: d.username, password: d.password }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#login-msg', r.message, 'err'); return; }
        f.reset(); say('#login-msg', '');
        if (r.user.must_change_password || !goNext()) refresh();
      });
    });

    $('#f-register').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      if (d.password !== d.password2) { say('#reg-msg', 'The two passwords don’t match.', 'err'); return; }
      GW.busy(f, true); say('#reg-msg', 'Creating your account…', 'info');
      GW.api('POST', '/auth/register', {
        username: d.username, password: d.password, updates: d.updates,
        email: d.updates ? d.email : '', website: d.website
      }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#reg-msg', r.message, 'err'); return; }
        f.reset(); show('#reg-email-row', false);
        say('#reg-msg', '');
        if (!goNext()) {
          refresh().then(function () { say('#in-msg', 'Welcome, ' + r.user.username + '.' + verificationNote(r.verification), 'ok'); });
        }
      });
    });

    $('#f-help').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      GW.busy(f, true); say('#help-msg', 'Sending…', 'info');
      GW.api('POST', '/contact', { kind: 'account-help', username: d.username, email: d.email,
                                   note: d.note, website: d.website }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#help-msg', r.message, 'err'); return; }
        f.reset();
        say('#help-msg', 'Sent. We’ll reply by email with a temporary password.', 'ok');
      });
    });

    $('#sign-out').addEventListener('click', function () {
      GW.signOut().then(function () { location.href = '/account/'; });
    });

    $('#f-updates').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      GW.busy(f, true);
      GW.api('PATCH', '/me', { updates: d.updates, email: d.email }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#up-msg', r.message, 'err'); return; }
        refresh().then(function () {
          say('#up-msg', d.updates ? 'Saved.' + verificationNote(r.verification)
                                   : 'Done. Your email address has been deleted.', 'ok');
        });
      });
    });

    $('#up-resend').addEventListener('click', function () {
      GW.api('POST', '/me/email/resend', {}).then(function (r) {
        say('#up-msg', r.ok ? (r.verification === 'sent' ? 'Sent. Check your inbox.' : 'Still couldn’t send. Try again later.')
                            : r.message, r.ok && r.verification === 'sent' ? 'ok' : 'err');
      });
    });

    $('#f-pass').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      if (d.new !== d.new2) { say('#pass-msg', 'The two new passwords don’t match.', 'err'); return; }
      GW.busy(f, true);
      GW.api('POST', '/me/password', { current: d.current, new: d.new }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#pass-msg', r.message, 'err'); return; }
        f.reset();
        say('#pass-msg', 'Password changed. Any other devices have been signed out.', 'ok');
        if (!goNext()) refresh();
      });
    });

    $('#f-delete').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      if (!d.sure) { say('#del-msg', 'Tick the box to confirm.', 'err'); return; }
      GW.busy(f, true);
      GW.api('POST', '/me/delete', { password: d.password }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#del-msg', r.message, 'err'); return; }
        location.href = '/account/?deleted=1';
      });
    });

    if (new URLSearchParams(location.search).get('deleted')) {
      say('#out-msg', 'Your account and everything stored with it has been deleted.', 'ok');
    }
    refresh();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
