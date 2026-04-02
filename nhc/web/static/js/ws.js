/**
 * WebSocket connection manager.
 */
const WS = {
  socket: null,
  sessionId: null,
  handlers: {},

  connect(sessionId) {
    this.sessionId = sessionId;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const token = document.cookie.match(/nhc_token=([^;]+)/)?.[1]
      || new URLSearchParams(location.search).get("token") || "";
    let url = `${proto}//${location.host}/ws/game/${sessionId}`;
    if (token) url += `?token=${encodeURIComponent(token)}`;
    this.socket = new WebSocket(url);

    this.socket.onopen = () => {
      console.log("WS connected:", sessionId);
    };

    this.socket.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      const handler = this.handlers[msg.type];
      if (handler) {
        handler(msg);
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
    this.handlers[type] = handler;
  },
};
