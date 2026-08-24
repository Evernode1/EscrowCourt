import { createClient } from "https://esm.sh/genlayer-js@0.28.0";
import { testnetBradbury } from "https://esm.sh/genlayer-js@0.28.0/chains";
import { TransactionStatus } from "https://esm.sh/genlayer-js@0.28.0/types";

let client = null;
let readOnlyClient = null;
let registryAddress = null;
let networkConfig = null;
let dealCode = null;

function maskAddress(a) { if (!a) return ''; return a.slice(0, 6) + '…' + a.slice(-4); }

function toGenDisplay(weiStr) {
  try {
    const wei = BigInt(weiStr || '0');
    const whole = wei / 1000000000000000000n;
    const frac = wei % 1000000000000000000n;
    if (frac === 0n) return whole.toString();
    const fracStr = (frac + 1000000000000000000n).toString().slice(1, 5).replace(/0+$/, '');
    return fracStr ? `${whole}.${fracStr}` : whole.toString();
  } catch { return '0'; }
}

function toGenWei(amountStr) {
  const [w, f = ''] = String(amountStr).split('.');
  const frac = (f + '000000000000000000').slice(0, 18);
  return (BigInt(w || '0') * 1000000000000000000n + BigInt(frac || '0')).toString();
}

async function fetchConfig() {
  if (registryAddress && networkConfig) return { registryAddress, networkConfig };
  const cfg = await (await fetch('/api/config')).json();
  registryAddress = cfg.registryAddress;
  networkConfig = cfg.network;
  return { registryAddress, networkConfig };
}

async function fetchDealCode() {
  if (dealCode) return dealCode;
  dealCode = await (await fetch('/deal-contract-source')).text();
  return dealCode;
}

async function getReadOnlyClient() {
  if (readOnlyClient) return readOnlyClient;
  readOnlyClient = createClient({ chain: testnetBradbury });
  return readOnlyClient;
}

// --- Multi-wallet discovery (EIP-6963) -------------------------------
// Modern EVM wallets (MetaMask, Trust Wallet, Coinbase Wallet, Rabby,
// OKX, Brave, Rainbow, etc.) each announce themselves via the
// 'eip6963:announceProvider' event so that multiple extensions can
// coexist without fighting over window.ethereum. We listen for those
// announcements and let the user pick which wallet to use.
const discoveredWallets = new Map(); // uuid -> { info, provider }

function listenForWallets() {
  window.addEventListener('eip6963:announceProvider', (event) => {
    const { info, provider } = event.detail || {};
    if (info && provider) discoveredWallets.set(info.uuid, { info, provider });
  });
  window.dispatchEvent(new Event('eip6963:requestProvider'));
}
listenForWallets();

function getLegacyProviderList() {
  // Some wallets (older Coinbase Wallet extension, some multi-wallet
  // setups) expose several providers via window.ethereum.providers
  // instead of using EIP-6963.
  if (window.ethereum && Array.isArray(window.ethereum.providers) && window.ethereum.providers.length) {
    return window.ethereum.providers;
  }
  return window.ethereum ? [window.ethereum] : [];
}

function walletLabel(p, fallback) {
  if (p.isMetaMask) return 'MetaMask';
  if (p.isCoinbaseWallet) return 'Coinbase Wallet';
  if (p.isTrust || p.isTrustWallet) return 'Trust Wallet';
  if (p.isRabby) return 'Rabby';
  if (p.isOkxWallet || p.isOKExWallet) return 'OKX Wallet';
  if (p.isBraveWallet) return 'Brave Wallet';
  if (p.isRainbow) return 'Rainbow';
  if (p.isFrame) return 'Frame';
  return fallback || 'Browser Wallet';
}

function showWalletPicker(options) {
  return new Promise((resolve) => {
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:200;display:flex;align-items:center;justify-content:center;padding:20px;';
    const box = document.createElement('div');
    box.style.cssText = 'background:#161616;border:1px solid #333;border-radius:12px;padding:20px;max-width:360px;width:100%;';
    const title = document.createElement('p');
    title.textContent = 'Choose a wallet';
    title.style.cssText = 'margin:0 0 14px;font-weight:600;';
    box.appendChild(title);
    options.forEach((opt) => {
      const btn = document.createElement('button');
      btn.className = 'btn btn--ghost';
      btn.style.cssText = 'display:flex;align-items:center;gap:10px;width:100%;margin-bottom:10px;text-align:left;';
      if (opt.icon) {
        const img = document.createElement('img');
        img.src = opt.icon; img.alt = ''; img.style.cssText = 'width:22px;height:22px;border-radius:5px;';
        btn.appendChild(img);
      }
      const span = document.createElement('span');
      span.textContent = opt.label;
      btn.appendChild(span);
      btn.addEventListener('click', () => { cleanup(); resolve(opt.provider); });
      box.appendChild(btn);
    });
    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'btn btn--ghost';
    cancelBtn.style.cssText = 'width:100%;margin-top:4px;';
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', () => { cleanup(); resolve(null); });
    box.appendChild(cancelBtn);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
    function cleanup() { overlay.remove(); }
  });
}

async function waitForEthereumProvider(timeoutMs = 1500) {
  // Give EIP-6963 announcements a brief moment to arrive.
  const start = Date.now();
  while (discoveredWallets.size === 0 && getLegacyProviderList().length === 0 && Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, 100));
  }

  const candidates = [];
  discoveredWallets.forEach(({ info, provider }) => {
    candidates.push({ provider, label: info.name || walletLabel(provider), icon: info.icon });
  });
  // Merge in any legacy-style providers not already covered by EIP-6963.
  getLegacyProviderList().forEach((p) => {
    const already = candidates.some((c) => c.provider === p);
    if (!already) candidates.push({ provider: p, label: walletLabel(p) });
  });

  if (candidates.length === 0) return null;
  if (candidates.length === 1) return candidates[0].provider;
  return showWalletPicker(candidates);
}

async function connectWalletAndEnsureNetwork() {
  const { networkConfig: net } = await fetchConfig();
  const provider = await waitForEthereumProvider();
  if (!provider) {
    throw new Error('No wallet found. Open this site from inside your wallet app’s built-in browser, or install a browser wallet extension (MetaMask, Trust Wallet, Coinbase Wallet, Rabby, OKX, etc.).');
  }
  // Point window.ethereum at the chosen wallet so downstream libraries
  // (which read window.ethereum directly for signing) use the same one.
  try { window.ethereum = provider; } catch (e) { /* some wallets freeze this; ignore */ }
  try {
    await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: net.chainIdHex }] });
  } catch (e) {
    if (e.code === 4902 || (e.data && e.data.originalError && e.data.originalError.code === 4902)) {
      await provider.request({
        method: 'wallet_addEthereumChain',
        params: [{
          chainId: net.chainIdHex,
          chainName: net.chainName,
          rpcUrls: net.rpcUrls,
          nativeCurrency: net.nativeCurrency,
          blockExplorerUrls: net.blockExplorerUrls,
        }],
      });
    } else {
      throw e;
    }
  }
  const accounts = await provider.request({ method: 'eth_requestAccounts' });
  return accounts[0];
}

function updateAccount(account) {
  try {
    if (!account) { client = null; return; }
    client = createClient({ chain: testnetBradbury, account });
  } catch (e) {
    console.error('Error updating account', e);
  }
}

function setUIConnected(address) {
  const addr = document.getElementById('addr'); if (addr) addr.textContent = maskAddress(address);
  const btn = document.getElementById('connectBtn'); if (btn) { btn.textContent = 'Disconnect'; btn.dataset.state = 'connected'; }
  document.querySelectorAll('.lockable').forEach((el) => el.classList.remove('is-locked'));
}

function setUIDisconnected() {
  const addr = document.getElementById('addr'); if (addr) addr.textContent = '';
  const btn = document.getElementById('connectBtn'); if (btn) { btn.textContent = 'Connect Wallet'; btn.dataset.state = 'disconnected'; }
  document.querySelectorAll('.lockable').forEach((el) => el.classList.add('is-locked'));
}

async function disconnect() {
  localStorage.removeItem('connectedAddress');
  client = null;
  setUIDisconnected();
}

async function connect() {
  const address = await connectWalletAndEnsureNetwork();
  localStorage.setItem('connectedAddress', address);
  updateAccount(address);
  setUIConnected(address);
  return address;
}

function isConnected() { return !!localStorage.getItem('connectedAddress'); }
function getAddress() { return localStorage.getItem('connectedAddress') || ''; }

async function ensureConnected() {
  if (!isConnected()) throw new Error('Please connect your wallet first');
  if (!client) updateAccount(getAddress());
  return getAddress();
}

let _wired = false;
function init() {
  if (_wired) return;
  _wired = true;
  const btn = document.getElementById('connectBtn');
  if (btn) {
    btn.dataset.state = 'disconnected';
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        if (btn.dataset.state === 'connected') await disconnect();
        else await connect();
      } catch (e) {
        alert(e.message || String(e));
      } finally {
        btn.disabled = false;
      }
    });
  }
  const saved = localStorage.getItem('connectedAddress');
  if (saved) {
    setUIConnected(saved);
    updateAccount(saved);
  } else {
    setUIDisconnected();
  }
}

// --- Registry helpers ---

async function readRegistry(functionName, args = []) {
  const { registryAddress: addr } = await fetchConfig();
  if (!addr) throw new Error('Registry address is not configured yet');
  const c = client || await getReadOnlyClient();
  return c.readContract({ address: addr, functionName, args });
}

// --- Deal contract helpers (arbitrary address, since each deal is its own contract) ---

let _writeInFlight = false;

async function readDeal(dealAddress, functionName, args = []) {
  const c = client || await getReadOnlyClient();
  return c.readContract({ address: dealAddress, functionName, args });
}

async function writeDeal(dealAddress, functionName, args = [], valueWei = '0') {
  if (_writeInFlight) throw new Error('Another transaction is already in progress. Please wait for it to finish.');
  if (!client) throw new Error('Wallet not connected');
  _writeInFlight = true;
  try {
    const hash = await client.writeContract({
      address: dealAddress,
      functionName,
      args,
      value: BigInt(valueWei || '0'),
    });
    return await client.waitForTransactionReceipt({ hash, status: TransactionStatus.ACCEPTED, retries: 200, interval: 5000 });
  } finally {
    _writeInFlight = false;
  }
}

// Deploys a brand-new Deal contract directly from the connected wallet — the
// user pays their own gas and signs the deployment themselves. There is no
// server-side wallet involved anywhere in this flow.
async function deployDeal({ buyer, freelancer, title, milestoneDescriptions, milestoneAmountsWei, createdAt, refundEnabled, refundDelaySeconds }) {
  if (_writeInFlight) throw new Error('Another transaction is already in progress. Please wait for it to finish.');
  if (!client) throw new Error('Wallet not connected');
  const { registryAddress: registry } = await fetchConfig();
  if (!registry) throw new Error('Registry address is not configured yet');
  const code = await fetchDealCode();
  _writeInFlight = true;
  try {
    const hash = await client.deployContract({
      code,
      args: [registry, buyer, freelancer, title, milestoneDescriptions, milestoneAmountsWei.map((v) => BigInt(v)), createdAt, Boolean(refundEnabled), Number(refundDelaySeconds || 0)],
    });
    const receipt = await client.waitForTransactionReceipt({ hash, status: TransactionStatus.ACCEPTED, retries: 200, interval: 5000 });
    return receipt.data?.contract_address ?? receipt.txDataDecoded?.contractAddress;
  } finally {
    _writeInFlight = false;
  }
}

async function readWithRetry(fn, retriesLeft = 3) {
  try {
    return await fn();
  } catch (e) {
    if (retriesLeft > 0) {
      await new Promise((r) => setTimeout(r, 2500));
      return readWithRetry(fn, retriesLeft - 1);
    }
    throw e;
  }
}

export {
  maskAddress,
  toGenDisplay,
  toGenWei,
  fetchConfig,
  getAddress,
  isConnected,
  ensureConnected,
  connect,
  disconnect,
  init,
  readRegistry,
  readDeal,
  writeDeal,
  deployDeal,
  readWithRetry,
};
