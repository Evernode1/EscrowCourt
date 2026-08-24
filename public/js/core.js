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

function waitForEthereumProvider(timeoutMs = 3000) {
  return new Promise((resolve) => {
    if (window.ethereum) return resolve(window.ethereum);
    const start = Date.now();
    const interval = setInterval(() => {
      if (window.ethereum) {
        clearInterval(interval);
        resolve(window.ethereum);
      } else if (Date.now() - start > timeoutMs) {
        clearInterval(interval);
        resolve(null);
      }
    }, 100);
    window.addEventListener('ethereum#initialized', () => {
      clearInterval(interval);
      resolve(window.ethereum);
    }, { once: true });
  });
}

async function connectWalletAndEnsureNetwork() {
  const { networkConfig: net } = await fetchConfig();
  const provider = await waitForEthereumProvider();
  if (!provider) {
    throw new Error('No wallet found. Open this site from inside your wallet app’s built-in browser, or install a browser wallet extension.');
  }
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
