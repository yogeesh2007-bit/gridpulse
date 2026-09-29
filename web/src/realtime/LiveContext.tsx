import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAuth } from "../auth/AuthContext";
import { getAccessToken, onTokenRefreshed, refreshSession } from "../lib/api";
import type { DriverSnapshot, OperatorState } from "../lib/types";

export type ConnectionState = "connecting" | "open" | "reconnecting" | "offline";

interface LiveValue {
  connection: ConnectionState;
  /** Latest full dashboard state pushed to operators. */
  operatorState: OperatorState | null;
  /** Latest reservations + public station view pushed to drivers. */
  driverSnapshot: DriverSnapshot | null;
  /** When the last message arrived (ms since epoch). */
  lastUpdate: number | null;
}

const LiveContext = createContext<LiveValue>({
  connection: "offline",
  operatorState: null,
  driverSnapshot: null,
  lastUpdate: null,
});

const TOKEN_EXPIRED = 4401;
const PING_EVERY_MS = 25_000;
const STALE_AFTER_MS = 20_000; // the server pushes every ~2 s; silence this long means a dead connection

const wsUrl = (token: string) => {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/ws?token=${encodeURIComponent(token)}`;
};

/** One authenticated WebSocket for the whole signed-in area, with backoff, token refresh and dead-link detection. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const [connection, setConnection] = useState<ConnectionState>("offline");
  const [operatorState, setOperatorState] = useState<OperatorState | null>(null);
  const [driverSnapshot, setDriverSnapshot] = useState<DriverSnapshot | null>(null);
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const [tokenVersion, setTokenVersion] = useState(0);
  const attempts = useRef(0);

  // reconnect with the new token whenever the access token is renewed
  useEffect(() => onTokenRefreshed((data) => data && setTokenVersion((v) => v + 1)), []);

  useEffect(() => {
    if (status !== "authed") {
      setConnection("offline");
      setOperatorState(null);
      setDriverSnapshot(null);
      return;
    }

    let disposed = false;
    let ws: WebSocket | null = null;
    let retryTimer: number | undefined;
    let pingTimer: number | undefined;
    let watchdog: number | undefined;
    let lastMessage = Date.now();

    const clearTimers = () => {
      window.clearTimeout(retryTimer);
      window.clearInterval(pingTimer);
      window.clearInterval(watchdog);
    };

    const scheduleReconnect = (immediate = false) => {
      if (disposed) return;
      setConnection("reconnecting");
      const delay = immediate ? 200 : Math.min(15_000, 1000 * 2 ** attempts.current);
      attempts.current += 1;
      retryTimer = window.setTimeout(connect, delay);
    };

    function connect() {
      if (disposed) return;
      const token = getAccessToken();
      if (!token) {
        scheduleReconnect();
        return;
      }
      setConnection((c) => (c === "open" ? c : attempts.current === 0 ? "connecting" : "reconnecting"));
      ws = new WebSocket(wsUrl(token));

      ws.onopen = () => {
        attempts.current = 0;
        lastMessage = Date.now();
        setConnection("open");
        window.clearInterval(pingTimer);
        window.clearInterval(watchdog);
        pingTimer = window.setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), PING_EVERY_MS);
        watchdog = window.setInterval(() => {
          if (Date.now() - lastMessage > STALE_AFTER_MS) ws?.close();
        }, 5_000);
      };

      ws.onmessage = (ev) => {
        lastMessage = Date.now();
        try {
          const msg = JSON.parse(ev.data as string) as { type: string; data?: unknown };
          if (msg.type === "state") setOperatorState(msg.data as OperatorState);
          else if (msg.type === "driver") setDriverSnapshot(msg.data as DriverSnapshot);
          else return; // hello / pong / error carry no state
          setLastUpdate(Date.now());
        } catch {
          /* ignore malformed frames */
        }
      };

      ws.onclose = async (ev) => {
        window.clearInterval(pingTimer);
        window.clearInterval(watchdog);
        if (disposed) return;
        if (ev.code === TOKEN_EXPIRED) {
          const renewed = await refreshSession(); // the token expired: get a new one, then reconnect at once
          if (!renewed) return; // session is gone; AuthContext sends the user to sign-in
          scheduleReconnect(true);
        } else {
          scheduleReconnect();
        }
      };
      ws.onerror = () => ws?.close();
    }

    connect();
    return () => {
      disposed = true;
      clearTimers();
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [status, tokenVersion]);

  const value = useMemo(
    () => ({ connection, operatorState, driverSnapshot, lastUpdate }),
    [connection, operatorState, driverSnapshot, lastUpdate],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);
