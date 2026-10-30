'use strict';
/* ====== Tiện ích ====== */
const $ = s => document.querySelector(s);
const app = $('#app');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = n => Number(n || 0).toLocaleString('vi-VN') + 'đ';
const when = d => new Date(d).toLocaleString('vi-VN', {hour12: false});
const ST = {pending:'Chờ xác nhận', preparing:'Đang pha chế', ready:'Sẵn sàng', completed:'Hoàn tất', cancelled:'Đã hủy'};
const TY = {dine_in:'Tại quán', takeaway:'Mang đi', delivery:'Giao hàng'};
const PAY = {cash:'Tiền mặt', transfer:'Chuyển khoản', momo:'MoMo'};
let CONFIG = {shippingFee: 15000, freeShipFrom: 150000};
let CATS = [];
const catColor = id => (CATS.find(c => c._id === id) || {}).color || '#6f4e37';
const catName = id => (CATS.find(c => c._id === id) || {}).name || id;

async function api(url, opt = {}) {
  const headers = {'Content-Type': 'application/json'};
  if (url.startsWith('/api/admin')) headers['X-Admin-Key'] = sessionStorage.getItem('adminKey') || '';
  const r = await fetch(url, {method: opt.method || 'GET', headers, body: opt.body ? JSON.stringify(opt.body) : undefined});
  let d = {};
  try { d = await r.json(); } catch (e) {}
  if (!r.ok) {
    let msg = d.detail;
    if (Array.isArray(msg)) msg = msg.map(x => (x.loc || []).slice(1).join('.') + ': ' + x.msg).join('; ');
    const err = new Error(msg || 'Có lỗi xảy ra');
    err.status = r.status;
    throw err;
  }
  return d;
}
let toastTimer;
function toast(msg, bad) {
  const t = $('#toast');
  t.textContent = msg; t.className = 'show' + (bad ? ' bad' : '');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.className = '', 3200);
}
const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

/* ====== Hình minh họa SVG theo nhóm món ====== */
function art(cat, color, size = 110) {
  const c = color || '#6f4e37';
  const S = {
    'ca-phe': `<ellipse cx="60" cy="108" rx="40" ry="5" fill="#d9c7b3"/><path d="M28 52h64v30a24 24 0 0 1-24 24H52a24 24 0 0 1-24-24z" fill="#fff" stroke="#4b2e1e" stroke-width="3"/><path d="M92 60h6a11 11 0 0 1 0 22h-8" fill="none" stroke="#4b2e1e" stroke-width="3"/><ellipse cx="60" cy="55" rx="30" ry="5" fill="${c}"/><path d="M46 38q-6-8 0-15M60 38q-6-8 0-15M74 38q-6-8 0-15" stroke="#b9a38f" stroke-width="3" fill="none" stroke-linecap="round"/>`,
    'tra': `<path d="M34 30h52l-6 76a8 8 0 0 1-8 7H48a8 8 0 0 1-8-7z" fill="#fff" fill-opacity=".6" stroke="#4b2e1e" stroke-width="3"/><path d="M38 52h44l-4 54H42z" fill="${c}" opacity=".85"/><circle cx="52" cy="70" r="6" fill="#f6b88c"/><circle cx="68" cy="84" r="6" fill="#f6b88c"/><path d="M66 12l8 54" stroke="#e0a02e" stroke-width="4" stroke-linecap="round"/>`,
    'sinh-to': `<path d="M32 28h56l-5 78a8 8 0 0 1-8 7H45a8 8 0 0 1-8-7z" fill="#fff" fill-opacity=".6" stroke="#4b2e1e" stroke-width="3"/><path d="M36 46h48l-3 60H39z" fill="${c}"/><circle cx="84" cy="30" r="10" fill="#9bc25a"/><path d="M62 10l6 50" stroke="#4b2e1e" stroke-width="4" stroke-linecap="round"/>`,
    'da-xay': `<path d="M32 40h56l-5 66a8 8 0 0 1-8 7H45a8 8 0 0 1-8-7z" fill="#fff" fill-opacity=".6" stroke="#4b2e1e" stroke-width="3"/><path d="M36 54h48l-3 52H39z" fill="${c}"/><path d="M32 40c0-14 14-18 28-18s28 4 28 18z" fill="#fff" stroke="#4b2e1e" stroke-width="3"/><path d="M60 8l4 30" stroke="#b03a2e" stroke-width="4" stroke-linecap="round"/>`,
    'banh': `<path d="M18 86l84-26V36L18 56z" fill="${c}" stroke="#4b2e1e" stroke-width="3" stroke-linejoin="round"/><path d="M18 56l84-20" stroke="#fff" stroke-width="6"/><path d="M18 86V70l84-24v14z" fill="#f3e6d4" stroke="#4b2e1e" stroke-width="3" stroke-linejoin="round" opacity=".9"/><circle cx="92" cy="30" r="7" fill="#b03a2e"/>`,
  };
  return `<svg viewBox="0 0 120 120" width="${size}" height="${size}" aria-hidden="true">${S[cat] || S['ca-phe']}</svg>`;
}
const stars = r => r && r.count ? `<span class="stars">★ ${r.avg} <span class="muted">(${r.count})</span></span>` : '<span class="muted">Chưa có đánh giá</span>';
const soldOut = it => it.trackStock && it.variants.every(v => (v.stock || 0) <= 0);

/* ====== Giỏ hàng (localStorage) ====== */
const cart = {
  get() { try { return JSON.parse(localStorage.getItem('cart') || '[]'); } catch (e) { return []; } },
  set(v) { localStorage.setItem('cart', JSON.stringify(v)); $('#badge').textContent = v.reduce((s, l) => s + l.qty, 0); },
};

/* ====== Router ====== */
const routes = [
  [/^#\/item\/([\w-]+)$/, m => itemPage(m[1]), 'menu'],
  [/^#\/cart$/, () => cartPage(), 'cart'],
  [/^#\/done$/, () => donePage(), 'cart'],
  [/^#\/orders$/, () => ordersPage(), 'orders'],
  [/^#\/admin$/, () => adminPage(), 'admin'],
];
async function route() {
  const h = location.hash || '#/';
  let nav = 'menu', fn = () => menuPage();
  for (const [re, f, n] of routes) { const m = h.match(re); if (m) { fn = () => f(m); nav = n; break; } }
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('on', a.dataset.nav === nav));
  window.scrollTo(0, 0);
  try { await fn(); } catch (e) { app.innerHTML = `<div class="card"><h3>Không tải được dữ liệu</h3><p class="muted">${esc(e.message)}</p></div>`; }
}
window.addEventListener('hashchange', route);

/* ====== Trang thực đơn ====== */
const M = {q: '', category: '', maxPrice: '', sort: 'popular', page: 1};
let searchTimer;
function menuPage() {
  app.innerHTML = `
    <div class="hero"><div><h1>Thưởng thức một ngày mới ☕</h1><p>Cà phê rang xay, trà trái cây và bánh nướng mỗi sáng.</p></div>
      <div class="muted" style="color:#ecdcc8">Giao hàng nội thành · Mang đi · Dùng tại quán</div></div>
    <div class="chips" id="chips"></div>
    <div class="toolbar">
      <input id="q" placeholder="Tìm món (vd: ca phe, tra dao...)" value="${esc(M.q)}" style="flex:1;min-width:200px">
      <select id="price"><option value="">Mọi mức giá</option><option value="30000">≤ 30.000đ</option><option value="40000">≤ 40.000đ</option><option value="50000">≤ 50.000đ</option></select>
      <select id="sort"><option value="popular">Bán chạy</option><option value="price_asc">Giá tăng dần</option><option value="price_desc">Giá giảm dần</option><option value="rating">Đánh giá cao</option><option value="name">Tên A-Z</option></select>
    </div>
    <div id="grid" class="grid"></div><div id="pager" class="pager"></div>`;
  $('#price').value = M.maxPrice; $('#sort').value = M.sort;
  $('#chips').innerHTML = [{_id: '', name: 'Tất cả'}, ...CATS].map(c =>
    `<span class="chip ${M.category === c._id ? 'on' : ''}" data-c="${esc(c._id)}">${esc(c.name)}</span>`).join('');
  $('#chips').onclick = e => { const c = e.target.closest('.chip'); if (c) { M.category = c.dataset.c; M.page = 1; menuPage(); } };
  $('#q').oninput = e => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { M.q = e.target.value; M.page = 1; loadMenu(); }, 300); };
  $('#price').onchange = e => { M.maxPrice = e.target.value; M.page = 1; loadMenu(); };
  $('#sort').onchange = e => { M.sort = e.target.value; M.page = 1; loadMenu(); };
  return loadMenu();
}
const loadMenu = guard(async () => {
  const p = new URLSearchParams({q: M.q, category: M.category, sort: M.sort, page: M.page, size: 12});
  if (M.maxPrice) p.set('maxPrice', M.maxPrice);
  const d = await api('/api/menu?' + p);
  $('#grid').innerHTML = d.items.length ? d.items.map(it => `
    <a class="item" href="#/item/${esc(it.slug)}">
      ${soldOut(it) ? '<span class="badge off">Hết hàng</span>' : ''}
      <div class="art">${art(it.category, catColor(it.category))}</div>
      <h3>${esc(it.name)}</h3><p class="muted">${esc(it.description)}</p>
      <div class="row between"><b>${it.variants.length > 1 ? 'từ ' : ''}${fmt(it.price)}</b>${stars(it.rating)}</div>
    </a>`).join('') : '<div class="card">Không tìm thấy món phù hợp.</div>';
  const pages = Math.max(1, Math.ceil(d.total / d.size));
  $('#pager').innerHTML = pages > 1 ? `<button class="sec sm" ${M.page <= 1 ? 'disabled' : ''} onclick="M.page--;loadMenu()">« Trước</button>
    <span class="muted">Trang ${M.page}/${pages} · ${d.total} món</span>
    <button class="sec sm" ${M.page >= pages ? 'disabled' : ''} onclick="M.page++;loadMenu()">Sau »</button>` : `<span class="muted">${d.total} món</span>`;
});

/* ====== Trang chi tiết món ====== */
let CUR = null;
async function itemPage(slug) {
  const d = await api('/api/menu/' + encodeURIComponent(slug));
  const it = CUR = d.item;
  const first = Math.max(0, it.variants.findIndex(v => !it.trackStock || v.stock > 0));
  app.innerHTML = `
    <p><a class="muted" href="#/">← Quay lại thực đơn</a></p>
    <div class="two">
      <div class="big-art">${art(it.category, catColor(it.category), 220)}</div>
      <div class="card">
        <span class="badge">${esc(catName(it.category))}</span>
        <h1>${esc(it.name)}</h1>
        <div class="row">${stars(it.rating)}<span class="muted">· Đã bán ${it.sold || 0}</span></div>
        <p>${esc(it.description)}</p>
        <b>Kích cỡ</b>
        <div class="opt">${it.variants.map((v, i) => { const out = it.trackStock && v.stock <= 0;
          return `<label style="${out ? 'opacity:.4' : ''}"><input type="radio" name="size" value="${esc(v.sku)}" ${i === first ? 'checked' : ''} ${out ? 'disabled' : ''} onchange="recalc()">${esc(v.size)} · ${fmt(v.price)}${it.trackStock ? ` <small>(còn ${v.stock})</small>` : ''}</label>`; }).join('')}</div>
        ${it.toppings.length ? `<b>Topping</b><div class="opt">${it.toppings.map(t =>
          `<label><input type="checkbox" name="top" value="${esc(t.name)}" onchange="recalc()">${esc(t.name)} +${fmt(t.price)}</label>`).join('')}</div>` : ''}
        ${it.customizable ? `<div class="row"><div><span class="muted">Độ ngọt</span><br><select id="sugar"><option value="100">100%</option><option value="70" selected>70%</option><option value="50">50%</option><option value="30">30%</option><option value="0">0%</option></select></div>
          <div><span class="muted">Đá</span><br><select id="ice"><option value="100" selected>100%</option><option value="50">50%</option><option value="0">Không đá</option></select></div></div><br>` : ''}
        <input id="note" placeholder="Ghi chú (tuỳ chọn)" maxlength="200" style="width:100%;margin-bottom:12px">
        <div class="row between"><div class="qty"><button class="sec" onclick="qtyStep(-1)">−</button><input id="q" type="number" value="1" min="1" max="20" style="width:64px;text-align:center" oninput="recalc()"><button class="sec" onclick="qtyStep(1)">+</button></div>
          <div class="price" id="price"></div></div><br>
        <button style="width:100%;padding:12px" onclick="addToCart()" ${soldOut(it) ? 'disabled' : ''}>${soldOut(it) ? 'Hết hàng' : 'Thêm vào giỏ hàng'}</button>
      </div>
    </div>
    ${it.ingredients.length ? `<div class="card"><h3>Nguyên liệu</h3><p class="muted">${it.ingredients.map(i => `${esc(i.name)} ${esc(i.qty)}${esc(i.unit)}`).join(' · ')}</p></div>` : ''}
    ${d.pairs.length ? `<h3>Dùng kèm</h3><div class="grid">${d.pairs.map(p => `<a class="item" href="#/item/${esc(p.slug)}"><div class="art">${art(p.category, catColor(p.category), 80)}</div><h3>${esc(p.name)}</h3><b>${fmt(p.price)}</b></a>`).join('')}</div><br>` : ''}
    <div class="card"><h3>Đánh giá (${it.rating.count})</h3>
      ${it.reviews.length ? it.reviews.map(r => `<div style="border-bottom:1px solid var(--line);padding:8px 0"><b>${esc(r.name)}</b> <span class="stars">${'★'.repeat(r.stars)}${'☆'.repeat(5 - r.stars)}</span> <span class="muted">${when(r.at)}</span><br>${esc(r.comment)}</div>`).join('') : '<p class="muted">Hãy là người đầu tiên đánh giá món này.</p>'}
      <div class="row" style="margin-top:12px"><input id="rn" placeholder="Tên của bạn" maxlength="60"><select id="rs"><option value="5">5 ★</option><option value="4">4 ★</option><option value="3">3 ★</option><option value="2">2 ★</option><option value="1">1 ★</option></select>
      <input id="rc" placeholder="Nhận xét" maxlength="500" style="flex:1;min-width:160px"><button onclick="sendReview('${esc(it.slug)}')">Gửi</button></div></div>
    <details><summary>Xem document MongoDB gốc của món này</summary><pre>${esc(JSON.stringify(it, null, 2))}</pre></details>`;
  recalc();
}
function selectedVariant() { const sku = document.querySelector('input[name=size]:checked'); return sku && CUR.variants.find(v => v.sku === sku.value); }
function selectedToppings() {
  const names = [...document.querySelectorAll('input[name=top]:checked')].map(x => x.value);
  return CUR.toppings.filter(t => names.includes(t.name));
}
function recalc() {
  const v = selectedVariant(); if (!v) { $('#price').textContent = ''; return; }
  const q = Math.min(20, Math.max(1, Number($('#q').value) || 1));
  $('#price').textContent = fmt((v.price + selectedToppings().reduce((s, t) => s + t.price, 0)) * q);
}
function qtyStep(n) { const e = $('#q'); e.value = Math.min(20, Math.max(1, (Number(e.value) || 1) + n)); recalc(); }
function addToCart() {
  const v = selectedVariant(); if (!v) return toast('Vui lòng chọn kích cỡ', true);
  const tops = selectedToppings();
  const line = {sku: v.sku, slug: CUR.slug, name: CUR.name, category: CUR.category, size: v.size, toppings: tops,
    sugar: CUR.customizable ? Number($('#sugar').value) : null, ice: CUR.customizable ? Number($('#ice').value) : null,
    note: $('#note').value.trim(), unit: v.price + tops.reduce((s, t) => s + t.price, 0), qty: Math.min(20, Math.max(1, Number($('#q').value) || 1))};
  const key = l => [l.sku, l.toppings.map(t => t.name).sort().join(','), l.sugar, l.ice, l.note].join('|');
  const lines = cart.get(), ex = lines.find(l => key(l) === key(line));
  if (ex) ex.qty = Math.min(20, ex.qty + line.qty); else lines.push(line);
  cart.set(lines); toast('Đã thêm vào giỏ hàng ✔');
}
const sendReview = guard(async slug => {
  await api(`/api/menu/${slug}/reviews`, {method: 'POST', body: {name: $('#rn').value, stars: Number($('#rs').value), comment: $('#rc').value}});
  toast('Cảm ơn bạn đã đánh giá!'); await itemPage(slug);
});

/* ====== Giỏ hàng & thanh toán ====== */
async function cartPage() {
  const lines = cart.get();
  if (!lines.length) { app.innerHTML = '<div class="card"><h2>Giỏ hàng trống</h2><p><a href="#/"><button>Xem thực đơn</button></a></p></div>'; return; }
  const me = JSON.parse(localStorage.getItem('me') || '{}');
  const free = (await api('/api/tables').catch(() => [])).filter(t => t.status === 'free');
  app.innerHTML = `<h2>Giỏ hàng</h2><div class="card">${lines.map((l, i) => `
    <div class="cartline"><div class="art">${art(l.category, catColor(l.category), 56)}</div>
      <div style="flex:1"><b>${esc(l.name)}</b> <span class="muted">(${esc(l.size)})</span>
        <div class="muted">${l.toppings.length ? '+ ' + l.toppings.map(t => esc(t.name)).join(', ') + ' · ' : ''}${l.sugar != null ? `Ngọt ${l.sugar}% · Đá ${l.ice}%` : ''}${l.note ? ' · “' + esc(l.note) + '”' : ''}</div></div>
      <div class="qty"><button class="sec sm" onclick="chg(${i},-1)">−</button><b>${l.qty}</b><button class="sec sm" onclick="chg(${i},1)">+</button></div>
      <b style="min-width:90px;text-align:right">${fmt(l.unit * l.qty)}</b><button class="bad sm" onclick="rm(${i})">✕</button></div>`).join('')}</div>
    <div class="card"><h3>Thông tin đặt hàng</h3><div class="form">
      <div><label>Họ tên *</label><input id="cn" value="${esc(me.name || '')}" maxlength="80"></div>
      <div><label>Số điện thoại * (10 số)</label><input id="cp" value="${esc(me.phone || '')}" maxlength="10" inputmode="numeric"></div>
      <div><label>Hình thức</label><select id="ct" onchange="typeChanged()">${free.length ? '<option value="dine_in">Dùng tại quán</option>' : ''}<option value="takeaway">Mang đi</option><option value="delivery">Giao hàng tận nơi</option></select></div>
      <div id="tblBox"><label>Chọn bàn trống</label><select id="ctb">${free.map(t => `<option value="${t.number}">Bàn ${t.number} · ${t.seats} chỗ · ${esc(t.area)}</option>`).join('')}</select></div>
      <div id="adrBox" class="hide"><label>Địa chỉ giao hàng *</label><input id="ca" maxlength="200"></div>
      <div><label>Thanh toán</label><select id="cm"><option value="cash">Tiền mặt</option><option value="transfer">Chuyển khoản</option><option value="momo">MoMo</option></select></div>
      <div style="grid-column:1/-1"><label>Ghi chú cho quán</label><input id="cnote" maxlength="300"></div></div>
      <div style="text-align:right;margin-top:14px"><div class="muted">Tạm tính: <span id="sub"></span></div><div class="muted">Phí giao hàng: <span id="ship"></span></div>
        <div class="price" id="tot"></div><br><button style="padding:12px 28px" onclick="submitOrder()">Đặt hàng</button></div></div>`;
  typeChanged();
}
function cartSubtotal() { return cart.get().reduce((s, l) => s + l.unit * l.qty, 0); }
function typeChanged() {
  const t = $('#ct').value, sub = cartSubtotal();
  $('#tblBox').classList.toggle('hide', t !== 'dine_in'); $('#adrBox').classList.toggle('hide', t !== 'delivery');
  const ship = t === 'delivery' && sub < CONFIG.freeShipFrom ? CONFIG.shippingFee : 0;
  $('#sub').textContent = fmt(sub);
  $('#ship').textContent = t === 'delivery' ? (ship ? fmt(ship) : 'Miễn phí (từ ' + fmt(CONFIG.freeShipFrom) + ')') : '—';
  $('#tot').textContent = fmt(sub + ship);
}
function chg(i, n) { const l = cart.get(); l[i].qty = Math.min(20, l[i].qty + n); if (l[i].qty < 1) l.splice(i, 1); cart.set(l); cartPage(); }
function rm(i) { const l = cart.get(); l.splice(i, 1); cart.set(l); cartPage(); }
let LAST = null;
const submitOrder = guard(async () => {
  const type = $('#ct').value, name = $('#cn').value.trim(), phone = $('#cp').value.trim();
  if (name.length < 2) throw new Error('Vui lòng nhập họ tên');
  if (!/^0\d{9}$/.test(phone)) throw new Error('Số điện thoại gồm 10 chữ số, bắt đầu bằng 0');
  const body = {customer: {name, phone}, type, paymentMethod: $('#cm').value, note: $('#cnote').value,
    tableNumber: type === 'dine_in' ? Number($('#ctb').value) : null, address: type === 'delivery' ? $('#ca').value : null,
    items: cart.get().map(l => ({sku: l.sku, qty: l.qty, toppings: l.toppings.map(t => t.name), sugar: l.sugar, ice: l.ice, note: l.note}))};
  LAST = await api('/api/orders', {method: 'POST', body});
  localStorage.setItem('me', JSON.stringify({name, phone}));
  cart.set([]); location.hash = '#/done';
});
function donePage() {
  if (!LAST) { location.hash = '#/'; return; }
  app.innerHTML = `<div class="card" style="text-align:center"><h1>🎉 Đặt hàng thành công!</h1><p>Mã đơn của bạn: <b style="font-size:22px">${esc(LAST.code)}</b></p>
    <p class="muted">Tra cứu trạng thái bằng số điện thoại ở mục “Đơn của tôi”.</p><a href="#/orders"><button>Đơn của tôi</button></a> <a href="#/"><button class="sec">Tiếp tục xem thực đơn</button></a></div>
    ${orderCard(LAST)}<details open><summary>Document vừa được lưu vào collection orders</summary><pre>${esc(JSON.stringify(LAST, null, 2))}</pre></details>`;
}

/* ====== Tra cứu đơn hàng ====== */
function orderCard(o, extra = '') {
  const path = ['pending', 'preparing', 'ready', 'completed'];
  const idx = path.indexOf(o.status);
  const steps = o.status === 'cancelled'
    ? `<span class="step done">${ST.pending}</span><span class="step x">${ST.cancelled}</span>`
    : path.map((s, i) => `<span class="step ${i < idx ? 'done' : i === idx ? 'cur' : ''}">${ST[s]}</span>`).join('');
  return `<div class="card"><div class="row between"><div><b>${esc(o.code)}</b> <span class="muted">· ${when(o.createdAt)}</span></div>
    <span class="badge">${TY[o.type]}${o.tableNumber ? ' · Bàn ' + o.tableNumber : ''}</span></div>
    <div class="steps">${steps}</div>
    ${o.items.map(l => `<div class="row between"><span>${l.qty}× ${esc(l.name)} <span class="muted">(${esc(l.variant)}${l.toppings.length ? ' + ' + l.toppings.map(t => esc(t.name)).join(', ') : ''})</span></span><span>${fmt(l.price * l.qty)}</span></div>`).join('')}
    ${o.address ? `<div class="muted">Giao đến: ${esc(o.address)}</div>` : ''}
    <div class="row between" style="margin-top:8px"><span class="muted">${PAY[o.paymentMethod]}${o.shippingFee ? ' · Phí giao ' + fmt(o.shippingFee) : ''}</span><b>${fmt(o.total)}</b></div>${extra}</div>`;
}
function ordersPage() {
  const me = JSON.parse(localStorage.getItem('me') || '{}');
  app.innerHTML = `<h2>Đơn hàng của tôi</h2><div class="card row"><input id="ph" placeholder="Nhập số điện thoại" value="${esc(me.phone || '')}" maxlength="10" inputmode="numeric">
    <button onclick="lookup()">Tra cứu</button><span class="muted">Dữ liệu mẫu: thử 0901234501</span></div><div id="res"></div>`;
  if (me.phone) lookup();
}
const lookup = guard(async () => {
  const d = await api('/api/orders?phone=' + encodeURIComponent($('#ph').value.trim()));
  $('#res').innerHTML = !d.customer ? '<div class="card">Chưa có đơn nào với số điện thoại này.</div>'
    : `<p>Xin chào <b>${esc(d.customer.name)}</b> · Điểm tích lũy: <b>${d.customer.points}</b></p>` + d.orders.map(o => orderCard(o)).join('');
});

/* ====== Quản trị ====== */
const A = {tab: 'stats', status: '', editSlug: null};
function adminPage() {
  if (!sessionStorage.getItem('adminKey')) {
    app.innerHTML = `<div class="card" style="max-width:420px;margin:40px auto"><h2>Đăng nhập quản trị</h2><p class="muted">Nhập mã quản trị (biến ADMIN_KEY trong file .env, mặc định admin123).</p>
      <div class="row"><input id="ak" type="password" placeholder="Mã quản trị" onkeydown="if(event.key==='Enter')adminLogin()"><button onclick="adminLogin()">Vào</button></div></div>`;
    return;
  }
  app.innerHTML = `<div class="row between"><h2>Trang quản trị</h2><button class="sec sm" onclick="sessionStorage.removeItem('adminKey');adminPage()">Đăng xuất</button></div>
    <div class="tabs">${[['stats', 'Thống kê'], ['orders', 'Đơn hàng'], ['tables', 'Bàn'], ['menu', 'Thực đơn'], ['report', 'Báo cáo tuần/tháng']].map(([k, n]) =>
      `<span class="chip ${A.tab === k ? 'on' : ''}" onclick="A.tab='${k}';adminPage()">${n}</span>`).join('')}</div><div id="adm"></div>`;
  return ({stats: adminStats, orders: adminOrders, menu: adminMenu, tables: adminTables, report: adminReport})[A.tab]();
}
const adminLogin = guard(async () => {
  sessionStorage.setItem('adminKey', $('#ak').value);
  try { await api('/api/admin/stats'); } catch (e) { sessionStorage.removeItem('adminKey'); throw e; }
  adminPage();
});
async function adminCall(fn) { try { await fn(); } catch (e) { if (e.status === 401) { sessionStorage.removeItem('adminKey'); adminPage(); } toast(e.message, true); } }

async function adminStats() { await adminCall(async () => {
  const d = await api('/api/admin/stats'), s = d.summary;
  const max = Math.max(1, ...d.byDay.map(x => x.revenue));
  const table = (rows, cols) => `<div class="scroll"><table><tr>${cols.map(c => `<th class="${c[2] || ''}">${c[0]}</th>`).join('')}</tr>${rows.map(r => `<tr>${cols.map(c => `<td class="${c[2] || ''}">${c[1](r)}</td>`).join('')}</tr>`).join('') || '<tr><td>Chưa có dữ liệu</td></tr>'}</table></div>`;
  $('#adm').innerHTML = `<div class="kpis"><div class="kpi"><span class="muted">Doanh thu</span><b>${fmt(s.revenue)}</b></div><div class="kpi"><span class="muted">Số đơn (không tính đơn hủy)</span><b>${s.orders}</b></div>
    <div class="kpi"><span class="muted">Giá trị đơn trung bình</span><b>${fmt(Math.round(s.avg))}</b></div>
    <div class="kpi"><span class="muted">Chờ xử lý</span><b>${(d.byStatus.find(x => x._id === 'pending') || {n: 0}).n + (d.byStatus.find(x => x._id === 'preparing') || {n: 0}).n}</b></div></div>
    <div class="card"><h3>Doanh thu 14 ngày gần nhất</h3><div class="bars" style="margin-bottom:26px">${d.byDay.map(x => `<div class="bar" title="${fmt(x.revenue)} · ${x.orders} đơn" style="height:${Math.max(2, x.revenue / max * 100)}%"><span>${esc(x._id)}</span></div>`).join('')}</div></div>
    <div class="cols"><div class="card"><h3>Doanh thu theo nhóm món</h3>${table(d.byCategory, [['Nhóm', r => esc(catName(r._id))], ['SL', r => r.qty, 'num'], ['Doanh thu', r => fmt(r.revenue), 'num']])}</div>
    <div class="card"><h3>Top 5 món bán chạy</h3>${table(d.topItems, [['Món', r => esc(r._id)], ['SL', r => r.qty, 'num'], ['Doanh thu', r => fmt(r.revenue), 'num']])}</div>
    <div class="card"><h3>Theo hình thức</h3>${table(d.byType, [['Hình thức', r => TY[r._id] || r._id], ['Đơn', r => r.n, 'num'], ['Doanh thu', r => fmt(r.revenue), 'num']])}</div>
    <div class="card"><h3>⚠ Bánh sắp hết (≤ 5)</h3>${table(d.lowStock, [['Món', r => esc(r.name) + ' <span class="muted">(' + esc(r.size) + ')</span>'], ['Còn', r => `<b style="color:var(--bad)">${r.stock}</b>`, 'num']])}</div></div>
    <div class="card"><h3>Đơn gần đây ($lookup điểm tích lũy từ customers)</h3>${table(d.recent, [['Mã', r => esc(r.code)], ['Khách', r => esc(r.customer.name)], ['Hình thức', r => TY[r.type]], ['Trạng thái', r => ST[r.status]], ['Điểm khách', r => r.points ?? 0, 'num'], ['Tổng', r => fmt(r.total), 'num']])}</div>`;
}); }

async function adminOrders() { await adminCall(async () => {
  const d = await api('/api/admin/orders?size=30&status=' + A.status);
  $('#adm').innerHTML = `<div class="toolbar"><select onchange="A.status=this.value;adminOrders()"><option value="">Tất cả trạng thái</option>${Object.keys(ST).map(k => `<option value="${k}" ${A.status === k ? 'selected' : ''}>${ST[k]}</option>`).join('')}</select><span class="muted">${d.total} đơn</span></div>` +
    d.items.map(o => orderCard(o, `<div class="row" style="margin-top:8px">${d.flow[o.status].map(s => `<button class="sm ${s === 'cancelled' ? 'bad' : 'ok'}" onclick="setStatus('${esc(o.code)}','${s}')">→ ${ST[s]}</button>`).join('')}<span class="muted">· ${esc(o.customer.name)} · ${esc(o.customer.phone)}</span></div>`)).join('');
}); }
const setStatus = async (code, s) => { await adminCall(async () => { await api(`/api/admin/orders/${code}/status`, {method: 'PATCH', body: {status: s}}); toast('Đã cập nhật'); }); adminOrders(); };

async function adminMenu() { await adminCall(async () => {
  const items = await api('/api/admin/menu');
  $('#adm').innerHTML = `<div class="card"><h3 id="mfTitle">Thêm món mới</h3><div class="form">
      <div><label>Tên món *</label><input id="mf_name" maxlength="100"></div>
      <div><label>Nhóm *</label><select id="mf_cat">${CATS.map(c => `<option value="${esc(c._id)}">${esc(c.name)}</option>`).join('')}</select></div>
      <div style="grid-column:1/-1"><label>Mô tả</label><input id="mf_desc" maxlength="300"></div>
      <div><label>Kích cỡ / giá — mỗi dòng: tên, giá[, tồn kho]</label><textarea id="mf_var" rows="3" placeholder="M, 35000&#10;L, 42000"></textarea></div>
      <div><label>Topping — mỗi dòng: tên, giá</label><textarea id="mf_top" rows="3" placeholder="Trân châu đen, 8000"></textarea></div>
      <div><label>Từ khóa (cách nhau bằng dấu phẩy)</label><input id="mf_tags"></div>
      <div><label><input type="checkbox" id="mf_track"> Theo dõi tồn kho (bánh)</label><label><input type="checkbox" id="mf_cust"> Cho chọn độ ngọt / đá (đồ uống)</label></div></div>
      <div class="row" style="margin-top:10px"><button onclick="saveItem()">Lưu món</button><button class="sec" onclick="A.editSlug=null;adminMenu()">Làm mới form</button></div></div>
    <div class="card scroll"><table><tr><th>Món</th><th>Nhóm</th><th>Giá</th><th>Kho</th><th>Đã bán</th><th>Trạng thái</th><th></th></tr>${items.map(it => `<tr>
      <td>${esc(it.name)}</td><td>${esc(catName(it.category))}</td><td>${it.variants.map(v => esc(v.size) + ' ' + fmt(v.price)).join('<br>')}</td>
      <td>${it.trackStock ? it.variants.map(v => v.stock).join(' / ') : '—'}</td><td>${it.sold || 0}</td>
      <td><span class="badge ${it.available ? 'ok' : 'off'}">${it.available ? 'Đang bán' : 'Ẩn'}</span></td>
      <td class="row"><button class="sec sm" onclick="editItem('${esc(it.slug)}')">Sửa</button><button class="sec sm" onclick="toggleItem('${esc(it.slug)}')">Ẩn/Hiện</button><button class="bad sm" onclick="delItem('${esc(it.slug)}')">Xóa</button></td></tr>`).join('')}</table></div>`;
  window.ADM_ITEMS = items;
}); }
function editItem(slug) {
  const it = ADM_ITEMS.find(x => x.slug === slug); A.editSlug = slug;
  $('#mfTitle').textContent = 'Sửa món: ' + it.name; $('#mf_name').value = it.name; $('#mf_name').disabled = true;
  $('#mf_cat').value = it.category; $('#mf_desc').value = it.description || '';
  $('#mf_var').value = it.variants.map(v => [v.size, v.price].concat(it.trackStock ? [v.stock] : []).join(', ')).join('\n');
  $('#mf_top').value = it.toppings.map(t => t.name + ', ' + t.price).join('\n'); $('#mf_tags').value = (it.tags || []).join(', ');
  $('#mf_track').checked = it.trackStock; $('#mf_cust').checked = it.customizable; window.scrollTo(0, 0);
}
const lines = id => $(id).value.split('\n').map(s => s.trim()).filter(Boolean).map(s => s.split(',').map(x => x.trim()));
const saveItem = guard(async () => {
  const track = $('#mf_track').checked;
  const body = {name: $('#mf_name').value, category: $('#mf_cat').value, description: $('#mf_desc').value, trackStock: track, customizable: $('#mf_cust').checked,
    variants: lines('#mf_var').map(p => ({size: p[0], price: Number(p[1]), stock: track && p[2] !== undefined && p[2] !== '' ? Number(p[2]) : null})),
    toppings: lines('#mf_top').map(p => ({name: p[0], price: Number(p[1])})),
    tags: $('#mf_tags').value.split(',').map(s => s.trim()).filter(Boolean)};
  if (A.editSlug) await api('/api/admin/menu/' + A.editSlug, {method: 'PUT', body}); else await api('/api/admin/menu', {method: 'POST', body});
  toast('Đã lưu món ✔'); A.editSlug = null; adminMenu();
});
const toggleItem = guard(async s => { await api(`/api/admin/menu/${s}/toggle`, {method: 'POST'}); adminMenu(); });
const delItem = guard(async s => { if (confirm('Xóa món này khỏi thực đơn?')) { await api('/api/admin/menu/' + s, {method: 'DELETE'}); adminMenu(); } });

/* ====== Quản lý bàn ====== */
const TS = {free: 'Trống', occupied: 'Có khách', reserved: 'Đã đặt trước', disabled: 'Tạm ngưng'};
function tableActions(t) {
  const n = t.number, b = (label, s, cls = 'sec') => `<button class="${cls} sm" onclick="setTable(${n},'${s}')">${label}</button>`;
  const by = {free: b('Đặt trước', 'reserved') + b('Tạm ngưng', 'disabled'), reserved: b('Khách đến → Trống', 'free') + b('Tạm ngưng', 'disabled'),
    disabled: b('Mở lại', 'free'), occupied: `<button class="sec sm" onclick="A.tab='orders';adminPage()">Xem đơn</button>`};
  return by[t.status] + `<button class="sec sm" onclick="editTable(${n})">Sửa</button>` + (t.status === 'occupied' ? '' : `<button class="bad sm" onclick="delTable(${n})">Xóa</button>`);
}
const tableCard = t => `<div class="tbl ${esc(t.status)}"><div class="row between"><b style="font-size:18px">Bàn ${t.number}</b><span class="badge">${TS[t.status]}</span></div>
  <div class="muted">${t.seats} chỗ ngồi</div>
  ${t.current ? `<div style="margin:6px 0"><b>${esc(t.current.code)}</b><br><span class="muted">${ST[t.current.status]} · ${fmt(t.current.total)}</span></div>` : ''}
  <div class="row" style="margin-top:8px">${tableActions(t)}</div></div>`;
async function adminTables() { await adminCall(async () => {
  const list = window.ADM_TABLES = await api('/api/admin/tables');
  const areas = [...new Set(list.map(t => t.area))];
  $('#adm').innerHTML = `<div class="kpis">${Object.keys(TS).map(s => `<div class="kpi"><span class="muted">${TS[s]}</span><b>${list.filter(t => t.status === s).length}</b></div>`).join('')}</div>
    <div class="card"><h3>Thêm bàn</h3><div class="form">
      <div><label>Số bàn bắt đầu (bỏ trống = tự đánh số tiếp)</label><input id="tb_num" type="number" min="1" max="999"></div>
      <div><label>Số lượng bàn cần thêm</label><input id="tb_cnt" type="number" min="1" max="50" value="1"></div>
      <div><label>Số chỗ ngồi mỗi bàn</label><input id="tb_seats" type="number" min="1" max="50" value="4"></div>
      <div><label>Khu vực</label><input id="tb_area" list="areas" value="${esc(areas[0] || 'Tầng 1')}" maxlength="40"><datalist id="areas">${areas.map(a => `<option value="${esc(a)}">`).join('')}</datalist></div></div>
      <div style="margin-top:10px"><button onclick="addTables()">+ Thêm bàn</button></div></div>
    ${areas.map(a => `<h3>${esc(a)}</h3><div class="tgrid">${list.filter(t => t.area === a).map(tableCard).join('')}</div>`).join('') || '<div class="card">Chưa có bàn nào.</div>'}`;
}); }
const addTables = guard(async () => {
  const num = $('#tb_num').value;
  const r = await api('/api/admin/tables', {method: 'POST', body: {number: num ? Number(num) : null, count: Number($('#tb_cnt').value) || 1, seats: Number($('#tb_seats').value) || 4, area: $('#tb_area').value}});
  toast('Đã thêm bàn ' + r.added.join(', ')); adminTables();
});
const setTable = guard(async (n, status) => {
  const t = ADM_TABLES.find(x => x.number === n);
  await api('/api/admin/tables/' + n, {method: 'PUT', body: {seats: t.seats, area: t.area, status}}); adminTables();
});
const editTable = guard(async n => {
  const t = ADM_TABLES.find(x => x.number === n);
  const seats = prompt('Số chỗ ngồi của bàn ' + n, t.seats); if (seats === null) return;
  const area = prompt('Khu vực', t.area); if (area === null) return;
  await api('/api/admin/tables/' + n, {method: 'PUT', body: {seats: Number(seats), area, status: t.status}}); toast('Đã cập nhật bàn ' + n); adminTables();
});
const delTable = guard(async n => { if (confirm('Xóa bàn ' + n + '?')) { await api('/api/admin/tables/' + n, {method: 'DELETE'}); adminTables(); } });

/* ====== Báo cáo tuần / tháng ====== */
const R = {type: 'week', date: ''};
let RPT = null;
const isoDate = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const change = (cur, prev, label) => (!prev ? '<span class="muted">—</span>' : cur >= prev
  ? `<span style="color:var(--ok)">▲ ${((cur - prev) / prev * 100).toFixed(1)}%</span>` : `<span style="color:var(--bad)">▼ ${((prev - cur) / prev * 100).toFixed(1)}%</span>`) + ` <span class="muted">so với ${esc(label)}</span>`;
const rtable = (rows, cols) => `<div class="scroll"><table><tr>${cols.map(c => `<th class="${c[2] || ''}">${c[0]}</th>`).join('')}</tr>${rows.map(r => `<tr>${cols.map(c => `<td class="${c[2] || ''}">${c[1](r)}</td>`).join('')}</tr>`).join('') || '<tr><td>Chưa có dữ liệu</td></tr>'}</table></div>`;
function rptQuick(type, offset) {
  const d = new Date();
  const base = type === 'week' ? new Date(d.getFullYear(), d.getMonth(), d.getDate() + 7 * offset) : new Date(d.getFullYear(), d.getMonth() + offset, 1);
  R.type = type; R.date = isoDate(base); adminReport();
}
async function adminReport() {
  if (!R.date) R.date = isoDate(new Date());
  $('#adm').innerHTML = `<div class="card"><h3>Xuất báo cáo doanh thu</h3><div class="row">
      <button class="sec sm" onclick="rptQuick('week',0)">Tuần này</button><button class="sec sm" onclick="rptQuick('week',-1)">Tuần trước</button>
      <button class="sec sm" onclick="rptQuick('month',0)">Tháng này</button><button class="sec sm" onclick="rptQuick('month',-1)">Tháng trước</button>
      <span class="muted">hoặc chọn:</span>
      <select id="rp_type" onchange="R.type=this.value;loadReport()"><option value="week">Theo tuần</option><option value="month">Theo tháng</option></select>
      <input id="rp_date" type="date" value="${esc(R.date)}" onchange="R.date=this.value;loadReport()">
      <button onclick="downloadReport()">⬇ Tải file Excel (.xlsx)</button></div>
    <p class="muted" style="margin-bottom:0">Chọn một ngày bất kỳ: báo cáo lấy cả tuần (thứ Hai – Chủ nhật) hoặc cả tháng chứa ngày đó. File Excel gồm 4 sheet: Tổng quan, Theo ngày (có biểu đồ), Phân tích, Đơn hàng.</p></div><div id="rp_body"></div>`;
  $('#rp_type').value = R.type;
  await loadReport();
}
async function loadReport() { await adminCall(async () => {
  const d = RPT = await api(`/api/admin/report?period=${R.type}&date=${encodeURIComponent(R.date)}`);
  const s = d.summary, p = d.prev, max = Math.max(1, ...d.byDay.map(x => x.revenue));
  $('#rp_body').innerHTML = `<h3>${esc(d.period.label)}</h3>
    <div class="kpis"><div class="kpi"><span class="muted">Doanh thu</span><b>${fmt(s.revenue)}</b>${change(s.revenue, p.revenue, p.label)}</div>
      <div class="kpi"><span class="muted">Số đơn hợp lệ</span><b>${s.orders}</b>${change(s.orders, p.orders, p.label)}</div>
      <div class="kpi"><span class="muted">Giá trị đơn trung bình</span><b>${fmt(s.avg)}</b></div>
      <div class="kpi"><span class="muted">Đơn bị hủy</span><b>${s.cancelled}</b></div>
      <div class="kpi"><span class="muted">Khách hàng</span><b>${s.customers}</b></div>
      <div class="kpi"><span class="muted">Số món bán ra</span><b>${s.itemsQty}</b></div></div>
    <div class="card"><h3>Doanh thu theo ngày</h3><div class="bars" style="margin-bottom:26px">${d.byDay.map(x => `<div class="bar" title="${esc(x.weekday)} ${esc(x.date)}: ${fmt(x.revenue)} · ${x.orders} đơn" style="height:${Math.max(2, x.revenue / max * 100)}%"><span>${esc(x.date.slice(0, 2))}</span></div>`).join('')}</div></div>
    <div class="cols"><div class="card"><h3>Theo nhóm món</h3>${rtable(d.byCategory, [['Nhóm', r => esc(catName(r._id))], ['SL', r => r.qty, 'num'], ['Doanh thu', r => fmt(r.revenue), 'num']])}</div>
      <div class="card"><h3>Top 10 món bán chạy</h3>${rtable(d.topItems, [['Món', r => esc(r._id)], ['SL', r => r.qty, 'num'], ['Doanh thu', r => fmt(r.revenue), 'num']])}</div>
      <div class="card"><h3>Theo hình thức</h3>${rtable(d.byType, [['Hình thức', r => TY[r._id] || esc(r._id)], ['Đơn', r => r.orders, 'num'], ['Doanh thu', r => fmt(r.revenue), 'num']])}</div>
      <div class="card"><h3>Theo thanh toán</h3>${rtable(d.byPayment, [['Phương thức', r => PAY[r._id] || esc(r._id)], ['Đơn', r => r.orders, 'num'], ['Doanh thu', r => fmt(r.revenue), 'num']])}</div></div>`;
}); }
const downloadReport = guard(async () => {
  const r = await fetch(`/api/admin/report?period=${R.type}&date=${encodeURIComponent(R.date)}&format=xlsx`, {headers: {'X-Admin-Key': sessionStorage.getItem('adminKey') || ''}});
  if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(typeof d.detail === 'string' ? d.detail : 'Không xuất được báo cáo'); }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(await r.blob());
  a.download = (RPT ? RPT.period.filename : 'bao-cao') + '.xlsx';
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  toast('Đã tải file báo cáo ✔');
});

/* ====== Khởi động ====== */
(async function init() {
  cart.set(cart.get());
  try { [CONFIG, CATS] = await Promise.all([api('/api/config'), api('/api/categories')]); }
  catch (e) { app.innerHTML = `<div class="card"><h3>Không kết nối được máy chủ</h3><p class="muted">${esc(e.message)}</p></div>`; return; }
  route();
})();
