function wageMoney(v){ return v ? `$${Number(v).toFixed(2)}/hr` : ''; }

function wageRange(low, high){
  if (!low) return '';
  return low === high || !high ? wageMoney(low) : `$${Number(low).toFixed(2)}–$${Number(high).toFixed(2)}/hr`;
}

function wageDate(w){
  if (!w || !w.effective_date) return '';
  const [y,m,d] = w.effective_date.split('-').map(Number);
  if (w.effective_precision === 'year') return `${y}`;
  const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  return w.effective_precision === 'month' ? `${months[m-1]} ${y}` : `${months[m-1]} ${d}, ${y}`;
}

function journeymanTile(l){
  const w = WAGE_DISPLAY ? l.wage : null;
  if (!w || !w.total_low) return { value: NOT_PUBLISHED, note: '' };
  const value = wageRange(w.total_low, w.total_high);
  const countyBit = (l.counties && l.counties[0]) ? esc(l.counties[0]) : '';
  const wd = w.wd_number ? esc(w.wd_number) : '';
  const bits = [wd ? `Davis-Bacon WD ${wd}` : 'Davis-Bacon prevailing wage', countyBit].filter(Boolean);
  return { value, note: bits.join(' &middot; ') };
}

function apprenticeTile(l){
  const a = WAGE_DISPLAY ? l.apprentice_wage : null;
  if (!a || a.kind === 'national_average') return NOT_PUBLISHED;
  if (a.kind === 'rapids_registration'){
    const median = a.start_hourly_low;
    return median ? `$${Number(median).toFixed(2)}/hr median reported` : NOT_PUBLISHED;
  }
  const start = wageRange(a.start_hourly_low, a.start_hourly_high);
  if (!start) return NOT_PUBLISHED;
  return a.start_pct ? `${start} (${Number(a.start_pct).toFixed(0)}% of journeyman base)` : start;
}

function apprenticeTileNote(l){
  const a = WAGE_DISPLAY ? l.apprentice_wage : null;
  if (!a) return '';
  if (a.kind === 'national_average') return 'Local data unavailable';
  if (a.kind === 'rapids_registration'){
    const n = a.record_count ? `, ${Number(a.record_count).toLocaleString()} records` : '';
    return `RAPIDS median at registration${n}`;
  }
  if (a.kind === 'jatc_published') return 'Local-published schedule';
  return 'Derived from Davis-Bacon';
}

function fyLabel(k){
  if (!k.period_start || !k.period_end) return '';
  const endYear = k.period_end.slice(0,4);
  return `FY${endYear}`;
}

function intakeTile(l){
  const intake = RAPIDS_DISPLAY ? l.intake : null;
  if (!intake) return { value: NOT_PUBLISHED, label: 'Annual intake', note: '', cls: '' };
  const fy = fyLabel(intake);
  if (intake.tier === 'confirmed'){
    return {
      value: fmt(intake.value), label: `Apprentices taken${fy?` (${fy})`:''}`,
      note: "Reported to the U.S. Department of Labor by this local's registered program.", cls: '',
    };
  }
  const note = INTAKE_CAVEAT === 'strong'
    ? "Rough estimate based on DOL-registered programs serving similarly sized jurisdictions. Intake varies widely between locals and year to year. Confirm with the JATC."
    : "Estimated from DOL-registered programs serving similarly sized jurisdictions. This local's own figure isn't in our data, and actual intake varies year to year. Confirm with the JATC.";
  return { value: `about ${fmt(intake.value)}`, label: 'Estimated annual intake', note, cls: 'est' };
}

function daysUntil(iso, today){
  const [y,m,d] = iso.split('-').map(Number);
  const target = new Date(y, m-1, d);
  const startOfToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - startOfToday) / 86400000);
}

function nextWindowTile(l, today){
  if (!STATUS_DISPLAY || !l.status) return NOT_PUBLISHED;
  const key = displayStatusKey(l.status, l.next_open);
  if (key === 'open_now') return 'Open now';
  if (key === 'always') return 'Always accepting';
  if (key === 'opens_date'){
    const days = daysUntil(l.next_open, today);
    if (days <= 0) return 'Open now';
    return `${fmtDate(l.next_open)} <small>(in ${days} day${days!==1?'s':''})</small>`;
  }
  return NOT_PUBLISHED;
}

function tilesBlockHTML(l, i, today){
  const jw = typeof journeymanTile === 'function' ? journeymanTile(l) : { value: NOT_PUBLISHED, note: '' };
  const appr = typeof apprenticeTile === 'function' ? apprenticeTile(l) : NOT_PUBLISHED;
  const apprNote = typeof apprenticeTileNote === 'function' ? apprenticeTileNote(l) : '';
  const win = nextWindowTile(l, today);
  const intake = typeof intakeTile === 'function' ? intakeTile(l) : { value: NOT_PUBLISHED, label: 'Annual intake', note: '', cls: '' };

  const cells = [];
  if (appr !== NOT_PUBLISHED) cells.push(`<div class="cell"><b>${appr}</b><span>Apprentice wage</span>
    ${apprNote?`<small>${esc(apprNote)}</small>`:''}</div>`);
  if (jw.value !== NOT_PUBLISHED) cells.push(`<div class="cell"><b>${jw.value}</b><span>Journeyman rate</span>
    ${jw.note?`<small>${jw.note}</small>`:''}</div>`);
  if (win !== NOT_PUBLISHED) cells.push(`<div class="cell"><b>${win}</b><span>Next application window</span></div>`);
  if (intake.value !== NOT_PUBLISHED) cells.push(`<div class="cell ${intake.cls}"><b>${intake.value}</b><span>${esc(intake.label)}</span>
    ${intake.note?`<small>${esc(intake.note)}</small>`:''}</div>`);

  if (!cells.length) return '';
  return `<div class="grid">${cells.join('')}</div>
  <div class="snote">Apprentice figures use the best available local-published schedule, RAPIDS registration wage, or clearly labeled derived fallback. Confirm the current scale with the local.</div>`;
}