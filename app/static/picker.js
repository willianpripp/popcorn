// The TMDB picker: type, pick, the hidden fields fill, the button unlocks.
// Titles always come from TMDB so posters and runtimes are real.
document.querySelectorAll('.picker').forEach(picker => {
  const form = document.getElementById(picker.dataset.form);
  const qEl = picker.querySelector('.pickq');
  const res = picker.querySelector('.pickresults');
  const picked = picker.querySelector('.picked');
  const go = form.querySelector('.go');
  const basePath = form.getAttribute('action').replace(/\/(request|watch)$/, '');
  let t;
  qEl.addEventListener('input', () => {
    clearTimeout(t);
    form.querySelector('[name=tmdb_id]').value = '';
    go.disabled = true;
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
        b.onclick = () => {
          form.querySelector('[name=tmdb_id]').value = it.tmdb_id;
          form.querySelector('[name=kind]').value = it.kind;
          const sbox = form.querySelector('.seasonbox');
          if (sbox) sbox.hidden = (it.kind !== 'series');
          picked.innerHTML = `✓ ${it.name} (${it.year || '?'})`;
          res.innerHTML = '';
          qEl.value = it.name;
          go.disabled = false;
        };
        res.appendChild(b);
      });
    }, 300);
  });
});
