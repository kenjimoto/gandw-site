/* /commissions/ and /commissions/req/ — the artist tracker and the access-request form. Needs gw.js. */
(function () {
  'use strict';
  var $ = GW.$, el = GW.el, say = GW.say, show = GW.show;
  var STATUS = { open: 'Open', earmarked: 'Earmarked', done: 'Done', closed: 'Closed' };

  function pill(status, mine) {
    return el('span', { class: 'pill pill--' + status, text: mine ? 'Earmarked by you' : STATUS[status] });
  }

  function facts(r) {
    var dl = el('dl', { class: 'reqfacts' });
    if (r.fee) dl.append(el('dt', { text: 'Fee' }), el('dd', { text: r.fee }));
    if (r.due) dl.append(el('dt', { text: 'Due' }), el('dd', { text: r.due }));
    dl.append(el('dt', { text: 'Posted' }), el('dd', { text: GW.date(r.created) }));
    return dl;
  }

  // ------------------------------------------------------------------ list page
  function listPage() {
    GW.me().then(function (me) {
      var signedIn = me.ok, user = me.ok ? me.user : null;
      show('#c-loading', false);
      if (me.error && me.error !== 'signed_out') { say('#c-state', me.message, 'err'); }
      else if (!signedIn) { show('#c-signedout', true); }
      else if (!GW.hasRole(user, 'artist')) {
        $('#c-who').textContent = user.username;
        show('#c-notyet', true);
        $('#acc-username').value = user.username;
      } else {
        show('#tracker', true);
        $('#t-who').textContent = user.username;
        loadReqs();
      }
    });

    $('#f-access').addEventListener('submit', function (e) {
      e.preventDefault();
      var f = e.target, d = GW.formData(f);
      GW.busy(f, true); say('#acc-msg', 'Sending…', 'info');
      GW.api('POST', '/contact', { kind: 'commission-access', username: d.username,
                                   email: d.email, note: d.note, website: d.website }).then(function (r) {
        GW.busy(f, false);
        if (!r.ok) { say('#acc-msg', r.message, 'err'); return; }
        f.reset();
        say('#acc-msg', 'Sent. We’ll reply by email once your account is on the artist list.', 'ok');
      });
    });
  }

  function loadReqs() {
    GW.api('GET', '/commissions/reqs').then(function (r) {
      var list = $('#reqs');
      list.textContent = '';
      if (!r.ok) { say('#t-msg', r.message, 'err'); return; }
      var mine = r.reqs.filter(function (x) { return x.mine; }).length;
      $('#t-held').textContent = mine + ' of ' + r.max_earmarks;
      r.reqs.forEach(function (q) {
        list.appendChild(el('li', { class: 'card req' + (q.mine ? ' req--mine' : '') },
          el('div', { class: 'req__head' },
            el('h3', { class: 'card__title' },
              el('a', { href: '/commissions/req/?id=' + encodeURIComponent(q.id), text: q.title })),
            pill(q.status, q.mine)),
          q.summary ? el('p', { class: 'card__dek', text: q.summary }) : null,
          facts(q),
          el('a', { class: 'req__more', href: '/commissions/req/?id=' + encodeURIComponent(q.id),
                    text: 'Read the brief →' })));
      });
      show('#reqs-empty', !r.reqs.length);
    });
  }

  // ------------------------------------------------------------------ detail page
  function detailPage() {
    var id = new URLSearchParams(location.search).get('id') || '';
    if (!/^[a-z0-9]+$/.test(id)) { show('#q-loading', false); say('#q-msg', 'No req was specified.', 'err'); return; }

    function draw(q) {
      show('#q-loading', false);
      show('#q-body', true);
      $('#q-title').textContent = q.title;
      document.title = q.title + ' · Commissions · Goggles & Windchimes';
      var head = $('#q-pill'); head.textContent = ''; head.appendChild(pill(q.status, q.mine));
      var f = $('#q-facts'); f.textContent = ''; f.appendChild(facts(q));
      $('#q-summary').textContent = q.summary || '';
      GW.paragraphs($('#q-desc'), q.description);
      show('#q-earmark', q.status === 'open');
      show('#q-release', q.mine);
      show('#q-mine-note', q.mine);
    }

    function act(path, okText) {
      GW.api('POST', '/commissions/reqs/' + id + path, {}).then(function (r) {
        if (!r.ok) { say('#q-msg', r.message, 'err'); return; }
        draw(r.req); say('#q-msg', okText, 'ok');
      });
    }
    $('#q-earmark').addEventListener('click', function () {
      act('/earmark', 'It’s yours. This req is now hidden from other artists. Reply to your invitation email to talk details.');
    });
    $('#q-release').addEventListener('click', function () {
      act('/release', 'Released. It’s back on the open list for other artists.');
    });

    GW.api('GET', '/commissions/reqs/' + id).then(function (r) {
      if (r.ok) { draw(r.req); return; }
      show('#q-loading', false);
      if (r.error === 'signed_out') {
        say('#q-msg', 'Sign in with your artist account to read this brief.', 'info');
        var a = $('#q-signin'); a.href = GW.accountUrl(location.pathname + location.search); show(a, true);
      } else say('#q-msg', r.message, 'err');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    if ($('#q-body')) detailPage(); else listPage();
  });
})();
