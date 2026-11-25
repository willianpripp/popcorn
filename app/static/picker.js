// The TMDB picker: type, pick, the hidden fields fill, the button unlocks.
// Titles always come from TMDB so posters and runtimes are real.
document.querySelectorAll('.picker').forEach(picker => {
  const form = document.getElementById(picker.dataset.form);
  const qEl = picker.querySelector('.pickq');
  const res = picker.querySelector('.pickresults');
  const picked = picker.querySelector('.picked');
  const go = form.querySelector('.go');
  const basePath = form.getAttribute('action').replace(/\/(request|watch(\/\d+\/edit)?)$/, '');
  let t;
  qEl.addEventListener('input', () => {
    clearTimeout(t);
    form.querySelector('[name=tmdb_id]').value = '';
    go.disabled = !(picker.dataset.optional && !qEl.value.trim());
    picked.textContent = '';
    t = setTimeout(async () => {
      const v = qEl.value.trim();
      if (v.length < 2) { res.innerHTML = ''; return; }
      const r = await fetch(`${basePath}/tmdb/search?query=${encodeURIComponent(v)}`);
      const items = await r.json();
      res.innerHTML = '';
      items.forEach(it => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'pickitem';
        b.innerHTML = `${it.poster ? `<img src="${it.poster}">` : '<span class="ph">🎬</span>'}
                       <span>${it.name} <small>${it.year || ''} · ${it.kind}</small></span>`;
        b.onclick = async () => {
          form.querySelector('[name=tmdb_id]').value = it.tmdb_id;
          form.querySelector('[name=kind]').value = it.kind;
          const sbox = form.querySelector('.seasonbox');
          if (sbox) sbox.hidden = (it.kind !== 'series');
          picked.innerHTML = `✓ ${it.name} (${it.year || '?'})`;
          res.innerHTML = '';
          qEl.value = it.name;
          go.disabled = false;
          // Where it streams is information only: Jellyfin is the library,
          // so the button is always a Jellyfin request.
          const availEl = form.querySelector('#availrow');
          if (availEl) {
            availEl.hidden = false;
            availEl.textContent = 'checking where it streams…';
            try {
              const pr = await (await fetch(`${basePath}/tmdb/providers?tmdb_id=${it.tmdb_id}&kind=${it.kind}`)).json();
              availEl.textContent = pr.streams.length
                ? `streams on ${pr.streams.join(', ')}`
                : 'not streaming';
            } catch (e) { availEl.hidden = true; }
          }
        };
        res.appendChild(b);
      });
    }, 300);
  });
});
