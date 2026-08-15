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
        b.onclick = async () => {
          form.querySelector('[name=tmdb_id]').value = it.tmdb_id;
          form.querySelector('[name=kind]').value = it.kind;
          const sbox = form.querySelector('.seasonbox');
          if (sbox) sbox.hidden = (it.kind !== 'series');
          picked.innerHTML = `✓ ${it.name} (${it.year || '?'})`;
          res.innerHTML = '';
          qEl.value = it.name;
          go.disabled = false;
          // Where does it stream? Household services decide the default:
          // streamable -> watchlist entry; nowhere we pay for -> Jellyfin.
          const availEl = form.querySelector('#availrow');
          const watchOn = form.querySelector('[name=watch_on]');
          if (availEl && watchOn) {
            watchOn.value = '';
            go.textContent = 'Request for Jellyfin';
            availEl.hidden = false;
            availEl.textContent = 'checking where it streams…';
            try {
              const pr = await (await fetch(`${basePath}/tmdb/providers?tmdb_id=${it.tmdb_id}&kind=${it.kind}`)).json();
              availEl.innerHTML = '';
              if (pr.mine.length) {
                watchOn.value = pr.mine[0];
                go.textContent = 'Add to watchlist';
                availEl.innerHTML = `<span class="avail-yes">✓ you have it: ${pr.mine.join(', ')}</span>`;
                const alt = document.createElement('button');
                alt.type = 'button'; alt.className = 'altbtn';
                alt.textContent = 'request for Jellyfin instead';
                alt.onclick = () => { watchOn.value = ''; go.textContent = 'Request for Jellyfin'; alt.remove(); };
                availEl.appendChild(alt);
              } else {
                availEl.innerHTML = pr.others.length
                  ? `<span class="avail-no">not on your services (streams on ${pr.others.join(', ')}) → Jellyfin</span>`
                  : `<span class="avail-no">not streaming anywhere → Jellyfin</span>`;
              }
            } catch (e) { availEl.hidden = true; }
          }
        };
        res.appendChild(b);
      });
    }, 300);
  });
});
