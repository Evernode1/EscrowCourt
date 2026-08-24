require('dotenv').config();
const express = require('express');
const morgan = require('morgan');
const cors = require('cors');
const path = require('path');
const fs = require('fs');

const app = express();
app.use(morgan('tiny'));
app.use(cors());
app.use(express.json());

// EscrowCourt has NO server-side wallet. The Registry is a single pre-deployed
// contract (its address is public); every Deal contract is deployed directly
// from the buyer's own wallet in the browser, using the source code served
// below. This removes server-side deployment entirely from the architecture.
const REGISTRY_ADDRESS = process.env.REGISTRY_ADDRESS || '';

const BRADBURY_NETWORK = {
  chainIdHex: '0x107D',
  chainName: 'GenLayer Bradbury',
  rpcUrls: ['https://rpc.testnet-chain.genlayer.com'],
  nativeCurrency: {
    name: process.env.NATIVE_CURRENCY_NAME || 'GEN',
    symbol: process.env.NATIVE_CURRENCY_SYMBOL || 'GEN',
    decimals: 18,
  },
  blockExplorerUrls: ['https://explorer.testnet-chain.genlayer.com'],
};

app.use(express.static(path.join(__dirname, '../public')));

const PAGES = ['create', 'deal', 'faq'];
PAGES.forEach((page) => {
  app.get(`/${page}`, (_req, res) => {
    res.sendFile(path.join(__dirname, `../public/${page}.html`));
  });
});

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, registryConfigured: Boolean(REGISTRY_ADDRESS) });
});

app.get('/api/config', (_req, res) => {
  res.json({
    registryAddress: REGISTRY_ADDRESS,
    network: BRADBURY_NETWORK,
  });
});

// Serves the raw Deal contract source so the browser can deploy it directly
// from the connected wallet — no backend deployment endpoint needed at all.
app.get('/deal-contract-source', (_req, res) => {
  res.type('text/plain').send(fs.readFileSync(path.join(__dirname, '../contracts/deal.py'), 'utf-8'));
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`EscrowCourt server listening on port ${PORT}`);
  if (!REGISTRY_ADDRESS) {
    console.warn('WARNING: REGISTRY_ADDRESS is not set. Deploy contracts/registry.py first, then set REGISTRY_ADDRESS.');
  }
});

module.exports = app;
