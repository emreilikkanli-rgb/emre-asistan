// claude.ai'nin `claude.use("db")` arayüzünü sunucudaki /api/db uç noktalarıyla taklit eder.
// Ajanda sayfası değişmeden çalışır; veriler sunucunun SQLite veritabanında durur.
window.EA_NO_PIN = true;
(function () {
  var csrf = (document.querySelector('meta[name="csrf"]') || {}).content || '';
  var subs = {};

  function api(method, path, body) {
    return fetch('/api/db/' + path, {
      method: method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF': csrf },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 401) { location.href = '/giris'; throw { code: 'revoked', message: 'Oturum kapandı' }; }
      if (r.status === 404) return null;
      if (r.status === 413) throw { code: 'quota_exceeded', message: 'Kayıt çok büyük' };
      if (!r.ok) throw { code: 'unavailable', message: 'HTTP ' + r.status };
      return r.status === 204 ? null : r.json();
    });
  }
  function snap(list) {
    var docs = list.map(function (x) { return { id: x.id, exists: true, data: function () { return x.data; } }; });
    return { docs: docs, size: docs.length, empty: !docs.length, docChanges: function () { return []; },
             metadata: { fromCache: false, hasPendingWrites: false } };
  }
  var last = {};
  function refresh(col, force) {
    return api('GET', col).then(function (list) {
      var key = JSON.stringify(list || []);
      if (!force && last[col] === key) return;  // değişiklik yoksa ekranı yeniden çizme (yarım formlar silinmesin)
      last[col] = key;
      (subs[col] || []).forEach(function (s) { s.next(snap(list || [])); });
    });
  }
  function refreshAll() { Object.keys(subs).forEach(function (c) { refresh(c).catch(function () {}); }); }
  setInterval(refreshAll, 5000);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refreshAll(); });

  function docRef(col, id) {
    var p = col + '/' + encodeURIComponent(id);
    return {
      id: id, path: col + '/' + id,
      get: function () {
        return api('GET', p).then(function (r) {
          return r ? { id: id, exists: true, data: function () { return r.data; } } : { id: id, exists: false, data: function () { return undefined; } };
        });
      },
      set: function (body) { return api('PUT', p, body).then(function () { refresh(col).catch(function () {}); }); },
      update: function (patch) {
        return api('GET', p).then(function (r) {
          if (!r) throw { code: 'invalid_argument', message: 'Kayıt yok' };
          return api('PUT', p, Object.assign({}, r.data, patch));
        }).then(function () { refresh(col).catch(function () {}); });
      },
      delete: function () { return api('DELETE', p).then(function () { refresh(col).catch(function () {}); }); }
    };
  }
  function colRef(col) {
    return {
      path: col,
      doc: function (id) { return docRef(col, id); },
      onSnapshot: function (next, error) {
        var entry = { next: next, error: error };
        (subs[col] = subs[col] || []).push(entry);
        refresh(col, true).catch(function (e) { if (error) error(e); });
        return function () { subs[col] = (subs[col] || []).filter(function (s) { return s !== entry; }); };
      }
    };
  }
  var db = {
    collection: colRef,
    doc: function (path) { var i = path.indexOf('/'); return docRef(path.slice(0, i), path.slice(i + 1)); }
  };
  window.claude = { use: function (name) { return Promise.resolve(name === 'db' ? db : null); } };
})();
