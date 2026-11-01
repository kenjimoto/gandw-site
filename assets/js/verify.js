/* /account/verify/ — confirm an update-email address from the emailed link. Needs gw.js. */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var t = new URLSearchParams(location.search).get('t');
    var msg = GW.$('#verify-msg');
    if (!t) { GW.say(msg, 'This page needs the link from your confirmation email.', 'err'); return; }
    // drop the token from the address bar and history once read
    history.replaceState(null, '', location.pathname);
    GW.api('POST', '/email/verify', { token: t }).then(function (r) {
      if (r.ok) GW.say(msg, 'Confirmed. You’ll hear from us when there’s something worth telling. Untick updates on your account page at any time and the address is deleted.', 'ok');
      else GW.say(msg, r.message, 'err');
    });
  });
})();
