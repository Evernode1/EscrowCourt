import * as core from './core.js';

core.init();
document.addEventListener('DOMContentLoaded', routePage);
routePage();

function routePage() {
  const path = window.location.pathname;
  if (path === '/' || path.endsWith('/index.html')) initHomePage();
  else if (path.startsWith('/create')) initCreatePage();
  else if (path.startsWith('/deal')) initDealPage();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function badgeClass(status) { return `badge badge--${status || 'pending'}`; }

// ---------------------------------------------------------------------
// TEXT MODAL (replaces window.prompt, which mobile in-app browsers block)
// ---------------------------------------------------------------------
function promptText(label, initial = '') {
  return new Promise((resolve) => {
    const modal = document.getElementById('textModal');
    const labelEl = document.getElementById('textModalLabel');
    const input = document.getElementById('textModalInput');
    const confirmBtn = document.getElementById('textModalConfirm');
    const cancelBtn = document.getElementById('textModalCancel');
    labelEl.textContent = label;
    input.value = initial;
    modal.style.display = 'flex';
    setTimeout(() => input.focus(), 50);
    const cleanup = (value) => {
      modal.style.display = 'none';
      confirmBtn.removeEventListener('click', onConfirm);
      cancelBtn.removeEventListener('click', onCancel);
      resolve(value);
    };
    const onConfirm = () => cleanup(input.value.trim() || null);
    const onCancel = () => cleanup(null);
    confirmBtn.addEventListener('click', onConfirm);
    cancelBtn.addEventListener('click', onCancel);
  });
}

function promptDeliverable() {
  return new Promise((resolve) => {
    const modal = document.getElementById('submitModal');
    const urlInput = document.getElementById('submitModalUrl');
    const descInput = document.getElementById('submitModalDesc');
    const confirmBtn = document.getElementById('submitModalConfirm');
    const cancelBtn = document.getElementById('submitModalCancel');
    urlInput.value = '';
    descInput.value = '';
    modal.style.display = 'flex';
    setTimeout(() => urlInput.focus(), 50);
    const cleanup = (value) => {
      modal.style.display = 'none';
      confirmBtn.removeEventListener('click', onConfirm);
      cancelBtn.removeEventListener('click', onCancel);
      resolve(value);
    };
    const onConfirm = () => {
      const url = urlInput.value.trim();
      const description = descInput.value.trim();
      if (!url && !description) { alert('Provide a URL, a description, or both.'); return; }
      cleanup({ url, description });
    };
    const onCancel = () => cleanup(null);
    confirmBtn.addEventListener('click', onConfirm);
    cancelBtn.addEventListener('click', onCancel);
  });
}

// ---------------------------------------------------------------------
// HOME PAGE
// ---------------------------------------------------------------------
let activeStatus = 'all';
let _homeWired = false;

async function initHomePage() {
  if (!_homeWired) {
    _homeWired = true;
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach((t) => t.addEventListener('click', () => {
      tabs.forEach((x) => x.classList.remove('is-active'));
      t.classList.add('is-active');
      activeStatus = t.dataset.status;
      loadDeals();
    }));
    window.addEventListener('walletchange', () => {
      if (activeStatus === 'mine') loadDeals();
    });
  }
  await loadDeals();
}

async function loadDeals() {
  const el = document.getElementById('sectionDeals');

  if (activeStatus === 'mine' && !core.isConnected()) {
    el.innerHTML = `<div class="empty-state"><div class="empty-state__title">Connect your wallet</div><p>Connect your wallet to see the deals you're a buyer or freelancer on.</p></div>`;
    return;
  }

  el.innerHTML = '<p class="form-hint">Loading deals…</p>';
  try {
    let fnName, args;
    if (activeStatus === 'mine') {
      fnName = 'get_deals_for_address';
      args = [core.getAddress(), 50];
    } else if (activeStatus === 'all') {
      fnName = 'get_deals';
      args = [50];
    } else {
      fnName = 'get_deals_by_status';
      args = [activeStatus, 50];
    }
    const raw = await core.readRegistry(fnName, args);
    const deals = JSON.parse(raw);
    renderDeals(deals, { showRole: activeStatus === 'mine' });
    updateStats(deals);
  } catch (e) {
    el.innerHTML = `<div class="empty-state"><div class="empty-state__title">Could not load deals</div><p>${escapeHtml(e.message || String(e))}</p></div>`;
  }
}

function renderDeals(deals, { showRole = false } = {}) {
  const el = document.getElementById('sectionDeals');
  if (!deals.length) {
    const message = showRole
      ? `You're not a buyer or freelancer on any deal yet.`
      : `Propose the first one from New Deal.`;
    el.innerHTML = `<div class="empty-state"><div class="empty-state__title">No deals yet</div><p>${message}</p></div>`;
    return;
  }
  const myAddress = showRole ? core.getAddress().toLowerCase() : '';
  el.innerHTML = deals.map((d) => {
    const role = showRole ? (d.buyer.toLowerCase() === myAddress ? 'Buyer' : 'Freelancer') : '';
    return `
    <a class="card" href="/deal?address=${encodeURIComponent(d.contract)}">
      <span class="${badgeClass(d.status)}">${d.status}</span>
      <p class="card__title">${escapeHtml(d.title)}</p>
      <div class="card__meta">
        <span>${core.toGenDisplay(d.total_amount)} GEN</span>
        <span>${showRole ? role + ' · ' : ''}${core.maskAddress(d.freelancer)}</span>
      </div>
    </a>
  `;
  }).join('');
}

function updateStats(deals) {
  const activeEl = document.getElementById('statActive');
  const totalEl = document.getElementById('statTotal');
  if (activeEl) activeEl.textContent = deals.filter((d) => d.status === 'active').length;
  if (totalEl) {
    const total = deals.reduce((sum, d) => sum + BigInt(d.total_amount || '0'), 0n);
    totalEl.textContent = core.toGenDisplay(total.toString());
  }
}

// ---------------------------------------------------------------------
// CREATE PAGE
// ---------------------------------------------------------------------
function initCreatePage() {
  if (!core.isConnected()) return;
  const rowsEl = document.getElementById('milestoneRows');
  const addBtn = document.getElementById('addMilestoneBtn');
  const form = document.getElementById('dealForm');
  if (!form || form.dataset.wired === 'true') return;
  form.dataset.wired = 'true';

  function addRow(desc = '', amount = '') {
    const row = document.createElement('div');
    row.className = 'milestone-row';
    row.innerHTML = `
      <textarea class="form-textarea m-desc" placeholder="Milestone requirement, e.g. 'Deliver a responsive homepage matching the approved Figma mockup'" style="min-height:60px;">${escapeHtml(desc)}</textarea>
      <input class="form-input m-amount" type="number" min="0.01" step="0.01" placeholder="GEN" value="${escapeHtml(amount)}" />
      <button type="button" class="milestone-remove">✕</button>
    `;
    row.querySelector('.milestone-remove').addEventListener('click', () => {
      if (rowsEl.children.length > 1) row.remove();
    });
    rowsEl.appendChild(row);
  }
  addRow();
  addBtn.addEventListener('click', () => addRow());

  const refundCheckbox = document.getElementById('d-refund-enabled');
  const refundDelayInput = document.getElementById('d-refund-delay');
  refundCheckbox.addEventListener('change', () => {
    refundDelayInput.style.display = refundCheckbox.checked ? 'block' : 'none';
  });

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const status = document.getElementById('statusMsg');
    const btn = document.getElementById('submitBtn');
    const title = document.getElementById('d-title').value.trim();
    const freelancer = document.getElementById('d-freelancer').value.trim();
    const descs = Array.from(rowsEl.querySelectorAll('.m-desc')).map((el) => el.value.trim());
    const amounts = Array.from(rowsEl.querySelectorAll('.m-amount')).map((el) => el.value.trim());

    if (!title || !freelancer) { status.textContent = 'Please fill in the title and freelancer address.'; return; }
    if (descs.some((d) => !d) || amounts.some((a) => !a || Number(a) <= 0)) {
      status.textContent = 'Every milestone needs a description and a positive GEN amount.';
      return;
    }

    btn.disabled = true;
    status.textContent = 'Deploying deal contract from your wallet… please confirm in your wallet app.';
    try {
      const buyer = await core.ensureConnected();
      const milestoneAmountsWei = amounts.map((a) => core.toGenWei(a));
      const refundEnabled = document.getElementById('d-refund-enabled').checked;
      const refundDelayHours = Number(document.getElementById('d-refund-delay').value || 0);
      const contractAddress = await core.deployDeal({
        buyer,
        freelancer,
        title,
        milestoneDescriptions: descs,
        milestoneAmountsWei,
        createdAt: Date.now(),
        refundEnabled,
        refundDelaySeconds: refundEnabled ? Math.round(refundDelayHours * 3600) : 0,
      });
      if (!contractAddress) throw new Error('Deployment succeeded but no contract address was returned. Check the Deals feed shortly.');
      status.textContent = 'Deployed. Redirecting to fund the escrow…';
      window.location.href = `/deal?address=${encodeURIComponent(contractAddress)}`;
    } catch (e) {
      status.textContent = e.message || String(e);
      btn.disabled = false;
    }
  });
}

// ---------------------------------------------------------------------
// DEAL DETAIL PAGE
// ---------------------------------------------------------------------
function getDealAddressFromUrl() {
  return new URLSearchParams(window.location.search).get('address');
}

let _dealWired = null;

async function initDealPage() {
  const address = getDealAddressFromUrl();
  document.getElementById('contractAddr').textContent = address || 'unknown';
  document.getElementById('dealId').textContent = address ? address.slice(0, 10) + '…' : '—';
  if (!address) {
    document.getElementById('dealTitle').textContent = 'Missing contract address in URL.';
    return;
  }
  if (_dealWired !== address) {
    _dealWired = address;
    wireFundButton(address);
  }
  await loadDeal(address);
}

function wireFundButton(address) {
  const status = document.getElementById('statusMsg');
  document.getElementById('btnFund').addEventListener('click', () => runAction(address, async () => {
    const raw = await core.readWithRetry(() => core.readDeal(address, 'get_deal_details', []));
    const d = JSON.parse(raw);
    await core.writeDeal(address, 'fund_escrow', [], d.total_amount);
  }));
}

let _isBusy = false;
async function runAction(address, fn) {
  const status = document.getElementById('statusMsg');
  if (_isBusy) return;
  _isBusy = true;
  setAllActionsDisabled(true);
  try {
    await core.ensureConnected();
    status.innerHTML = '<span class="form-hint">Submitting transaction… this can take a while if AI review is involved.</span>';
    await fn();
    status.textContent = 'Done.';
    await loadDeal(address);
  } catch (e) {
    // The write may have gone through on-chain even if the browser lost track
    // of it (common on mobile when switching to a wallet app). Re-check state
    // before showing a hard error.
    status.textContent = 'Confirming on-chain state…';
    try {
      await loadDeal(address);
      status.textContent = 'If your transaction actually succeeded, the details above should now reflect it. Otherwise: ' + (e.message || String(e));
    } catch {
      status.textContent = e.message || String(e);
    }
  } finally {
    _isBusy = false;
    setAllActionsDisabled(false);
  }
}

function setAllActionsDisabled(disabled) {
  document.querySelectorAll('#sectionFund button, #sectionMilestones button').forEach((el) => { el.disabled = disabled; });
}

async function loadDeal(address, retriesLeft = 3) {
  try {
    const raw = await core.readDeal(address, 'get_deal_details', []);
    const d = JSON.parse(raw);
    renderDeal(address, d);
  } catch (e) {
    if (retriesLeft > 0) {
      await new Promise((r) => setTimeout(r, 2500));
      return loadDeal(address, retriesLeft - 1);
    }
    document.getElementById('dealTitle').textContent = 'Could not load this deal.';
    throw e;
  }
}

function renderDeal(address, d) {
  document.getElementById('dealTitle').textContent = d.title;
  document.getElementById('dealMeta').textContent =
    `Buyer ${core.maskAddress(d.buyer)} · Freelancer ${core.maskAddress(d.freelancer)} · Total ${core.toGenDisplay(d.total_amount)} GEN`;

  const funded = d.funded === 'True' || d.funded === 'true';
  const fundSection = document.getElementById('sectionFund');
  fundSection.style.display = funded ? 'none' : 'block';
  fundSection.classList.remove('is-locked');

  const milestonesSection = document.getElementById('sectionMilestones');
  milestonesSection.classList.remove('is-locked');

  if (!funded) {
    milestonesSection.innerHTML = '<p class="form-hint">Milestones will appear here once the deal is funded.</p>';
    return;
  }

  milestonesSection.innerHTML = d.milestones.map((m) => renderMilestoneCard(address, m, d)).join('');
  wireMilestoneActions(address, d);
}

function renderMilestoneCard(address, m, d) {
  const status = m.status;
  const refundEnabled = d.refund_enabled === 'True' || d.refund_enabled === 'true';
  let actionsHtml = '';
  if (status === 'pending' || status === 'rejected') {
    actionsHtml += `<button class="btn btn--ghost btn--sm act-submit" data-index="${m.index}">Submit Deliverable</button>`;
  }
  if (status === 'submitted') {
    actionsHtml += `<button class="btn btn--ghost btn--sm act-review" data-index="${m.index}">Run AI Review</button>`;
  }
  if (status === 'rejected') {
    actionsHtml += `<button class="btn btn--ghost btn--sm act-evidence" data-index="${m.index}">Submit Dispute Evidence</button>`;
    actionsHtml += `<button class="btn btn--ghost btn--sm act-resolve" data-index="${m.index}">Resolve Dispute (Final)</button>`;
  }
  if (status === 'approved') {
    actionsHtml += `<button class="btn btn--brass btn--sm act-claim-payment" data-index="${m.index}">Claim Payment</button>`;
  }
  if (status === 'refunded') {
    actionsHtml += `<button class="btn btn--brass btn--sm act-claim-refund" data-index="${m.index}">Claim Refund</button>`;
  }
  if (status === 'pending' && refundEnabled) {
    actionsHtml += `<button class="btn btn--ghost btn--sm act-timeout-refund" data-index="${m.index}">Claim Timeout Refund</button>`;
  }
  if (['pending', 'submitted', 'rejected'].includes(status)) {
    const buyerVoted = m.buyer_cancel_vote === 'True' || m.buyer_cancel_vote === 'true';
    const freelancerVoted = m.freelancer_cancel_vote === 'True' || m.freelancer_cancel_vote === 'true';
    const voteLabel = buyerVoted || freelancerVoted ? 'Confirm Mutual Cancel' : 'Propose Cancel';
    actionsHtml += `<button class="btn btn--ghost btn--sm act-cancel" data-index="${m.index}">${voteLabel}</button>`;
  }
  if (m.reasoning) {
    actionsHtml += `<button class="btn btn--ghost btn--sm act-raw" data-index="${m.index}">View Raw AI Response</button>`;
  }

  let evidenceHtml = '';
  if (m.buyer_evidence || m.freelancer_evidence) {
    evidenceHtml = `<div class="milestone-card__section">
      ${m.buyer_evidence ? `<div><strong>Buyer:</strong> ${escapeHtml(m.buyer_evidence)}</div>` : ''}
      ${m.freelancer_evidence ? `<div><strong>Freelancer:</strong> ${escapeHtml(m.freelancer_evidence)}</div>` : ''}
    </div>`;
  }

  const deliverableHtml = (m.deliverable_url || m.deliverable_description)
    ? `<div class="milestone-card__section">
        ${m.deliverable_url ? `<div><strong>URL:</strong> <a href="${escapeHtml(m.deliverable_url)}" target="_blank" rel="noopener" style="color:var(--brass);">${escapeHtml(m.deliverable_url)}</a></div>` : ''}
        ${m.deliverable_description ? `<div><strong>Description:</strong> ${escapeHtml(m.deliverable_description)}</div>` : ''}
      </div>`
    : '';

  return `
    <div class="milestone-card">
      <div class="milestone-card__head">
        <div>
          <div class="form-hint" style="margin-bottom:6px;">Milestone ${m.index + 1}</div>
          <div class="milestone-card__desc">${escapeHtml(m.description)}</div>
        </div>
        <div style="text-align:right;">
          <span class="${badgeClass(status)}">${status}</span>
          <div class="milestone-card__amount">${core.toGenDisplay(m.amount)} GEN</div>
        </div>
      </div>
      ${deliverableHtml}
      ${m.reasoning ? `<div class="milestone-card__section"><strong>AI reasoning:</strong> ${escapeHtml(m.reasoning)}</div>` : ''}
      ${evidenceHtml}
      <div class="milestone-card__actions">${actionsHtml}</div>
    </div>
  `;
}

function wireMilestoneActions(address, dealDetails) {
  document.querySelectorAll('.act-submit').forEach((btn) => btn.addEventListener('click', () => runAction(address, async () => {
    const index = Number(btn.dataset.index);
    const deliverable = await promptDeliverable();
    if (!deliverable) throw new Error('Cancelled');
    await core.writeDeal(address, 'submit_milestone', [index, deliverable.url, deliverable.description]);
  })));

  document.querySelectorAll('.act-review').forEach((btn) => btn.addEventListener('click', () => runAction(address, async () => {
    const index = Number(btn.dataset.index);
    await core.writeDeal(address, 'review_milestone', [index]);
  })));

  document.querySelectorAll('.act-evidence').forEach((btn) => btn.addEventListener('click', () => runAction(address, async () => {
    const index = Number(btn.dataset.index);
    const evidence = await promptText('Your statement / evidence for this dispute');
    if (!evidence) throw new Error('Cancelled');
    await core.writeDeal(address, 'submit_dispute_evidence', [index, evidence]);
  })));

  document.querySelectorAll('.act-resolve').forEach((btn) => btn.addEventListener('click', () => runAction(address, async () => {
    const index = Number(btn.dataset.index);
    await core.writeDeal(address, 'resolve_dispute', [index]);
  })));

  document.querySelectorAll('.act-claim-payment').forEach((btn) => btn.addEventListener('click', () => runAction(address, async () => {
    const index = Number(btn.dataset.index);
    await core.writeDeal(address, 'claim_payment', [index]);
  })));

  document.querySelectorAll('.act-claim-refund').forEach((btn) => btn.addEventListener('click', () => runAction(address, async () => {
    const index = Number(btn.dataset.index);
    await core.writeDeal(address, 'claim_refund', [index]);
  })));

  document.querySelectorAll('.act-timeout-refund').forEach((btn) => btn.addEventListener('click', () => runAction(address, async () => {
    const index = Number(btn.dataset.index);
    await core.writeDeal(address, 'claim_timeout_refund', [index, Date.now()]);
  })));

  document.querySelectorAll('.act-cancel').forEach((btn) => btn.addEventListener('click', () => runAction(address, async () => {
    const index = Number(btn.dataset.index);
    const confirmed = confirm('Propose cancelling this milestone? Once BOTH buyer and freelancer confirm, the funds refund to the buyer immediately.');
    if (!confirmed) throw new Error('Cancelled');
    await core.writeDeal(address, 'propose_cancel', [index]);
  })));

  document.querySelectorAll('.act-raw').forEach((btn) => btn.addEventListener('click', async () => {
    const index = Number(btn.dataset.index);
    try {
      const raw = await core.readDeal(address, 'get_last_raw_response', [index]);
      alert(raw || '(no raw response recorded)');
    } catch (e) {
      alert(e.message || String(e));
    }
  }));
}
