"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ClassicHud from "./ClassicHud";

export default function JarvisOrb() {
  const [audioLevel, setAudioLevel] = useState<number>(0);
  
  // Custom states from Mark-L
  const [orbStatus, setOrbStatus] = useState<string>("ONLINE");
  const [orbText, setOrbText] = useState<string>("INITIALIZED");

  // Keep a ref to WebSocket
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Connect to python websocket server
    const connectWs = () => {
      const ws = new WebSocket("ws://127.0.0.1:8765");
      wsRef.current = ws;
      
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "get_files" }));
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "audio_level" && typeof data.level === "number") {
            setAudioLevel(data.level);
          } else if (data.type === "status" && typeof data.status === "string") {
            setOrbStatus(data.status.toUpperCase());
          } else if (data.type === "text" && typeof data.text === "string") {
            setOrbText(data.text);
          }
        } catch (e) {
          console.error("Error processing websocket message", e);
        }
      };

      ws.onclose = () => {
        setTimeout(connectWs, 2000);
      };
      
      ws.onerror = (e) => {
        console.error("WebSocket error:", e);
      };
    };

    connectWs();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  return (
    <div style={{ position: "relative", width: "100%", height: "100%", background: "#000", overflow: "hidden" }}>
      <ClassicHud audioLevel={audioLevel} orbText={orbText} orbStatus={orbStatus} />
    </div>
  );
}
