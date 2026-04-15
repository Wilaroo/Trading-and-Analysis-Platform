const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function(app) {
  // Chat routes → dedicated chat server (port 8002)
  app.use(
    '/api/sentcom/chat',
    createProxyMiddleware({
      target: 'http://localhost:8002',
      changeOrigin: true,
      pathRewrite: {
        '^/api/sentcom/chat/history': '/chat/history',
        '^/api/sentcom/chat': '/chat',
      },
    })
  );

  // Everything else → main backend (port 8001)
  app.use(
    '/api',
    createProxyMiddleware({
      target: 'http://localhost:8001',
      changeOrigin: true,
    })
  );
};
