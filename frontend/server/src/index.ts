import express from 'express';
import cors from 'cors';
import path from 'path';
import { createProxyMiddleware } from 'http-proxy-middleware';

const app = express();
const PORT = process.env.PORT || 4200;
const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:8000';

app.use(cors());

app.use(
  '/api',
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    pathRewrite: (_path) => `/api/v1${_path}`,
  })
);

app.use(
  '/mcp',
  createProxyMiddleware({
    target: BACKEND_URL,
    changeOrigin: true,
    pathRewrite: (_path) => `/mcp${_path}`,
  })
);

const clientDist = path.join(__dirname, '../../client/dist/client/browser');
app.use(express.static(clientDist));

app.get('/{*path}', (_req, res) => {
  res.sendFile(path.join(clientDist, 'index.html'));
});

app.listen(PORT, () => {
  console.log(`BFF server running on http://localhost:${PORT}`);
  console.log(`Proxying /api/* -> ${BACKEND_URL}/api/v1/*`);
  console.log(`Proxying /mcp/* -> ${BACKEND_URL}/mcp/*`);
  console.log(`Serving Angular from ${clientDist}`);
});
