/**
 * WebSocket connection manager.
 */
const WS = {
  socket: null,
  sessionId: null,
  handlers: {},

  connect(sessionId) {
    // Close any existing connection before opening a new one
    if (this.socket) {
      this.socket.onclose = null;  // suppress stale close handler
      this.socket.close();
      this.socket = null;
    }
    this.sessionId = sessionId;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    // The browser sends the ``nhc_token`` HttpOnly cookie on the
    // same-origin WebSocket handshake automatically; the server
    // reads the token from there.  Only fall back to the URL for
    // the legacy unauth path where no cookie is in play.
    const token = new URLSearchParams(location.search).get("token") || "";
    let url = `${proto}//${location.host}/ws/game/${sessionId}`;
    if (token) url += `?token=${encodeURIComponent(token)}`;
    this.socket = new WebSocket(url);

    this.socket.onopen = () => {
      console.log("WS connected:", sessionId);
    };

    this.socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      const handlers = this.handlers[msg.type];
      if (handlers && handlers.length) {
        handlers.forEach(h => {
          try { h(msg); } catch (err) {
            console.error("WS handler error for", msg.type, err);
          }
        });
      } else {
        console.warn("Unhandled WS message type:", msg.type);
      }
    };

    this.socket.onclose = () => {
      console.log("WS disconnected");
    };

    this.socket.onerror = (err) => {
      console.error("WS error:", err);
    };
  },

  send(msg) {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(msg));
    }
  },

  on(type, handler) {
    // Allow multiple handlers per message type so independent
    // modules (e.g. map.js + hex_map.js both listening to "state")
    // can coexist.
    if (!this.handlers[type]) this.handlers[type] = [];
    this.handlers[type].push(handler);
  },
};
