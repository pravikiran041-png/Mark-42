"use client";

import React from "react";
import "./ClassicHud.css";

interface ClassicHudProps {
  audioLevel: number;
  orbText?: string;
  orbStatus?: string;
}

export default function ClassicHud({ audioLevel, orbText = "SYSTEM ONLINE", orbStatus = "STANDBY" }: ClassicHudProps) {
  const coreScale = 1.0 + (audioLevel * 0.3);
  const ringSpeed = audioLevel > 0.1 ? "2s" : "8s";

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, width: '100vw', height: '100vh',
      background: '#000000', overflow: 'hidden', fontFamily: '"Orbitron", monospace', color: '#00d4ff',
      display: 'flex', justifyContent: 'center', alignItems: 'center'
    }}>
      <style>
        {`
          @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&display=swap');
          .orb-circle {
            transform-origin: 90px 90px;
          }
        `}
      </style>

      <div style={{ position: 'relative', width: '300px', height: '300px', transform: `scale(${coreScale})`, transition: 'transform 0.1s ease-out' }}>
        <svg viewBox="0 0 180 180" style={{width: '100%', height: '100%', filter: 'drop-shadow(0 0 15px #00d4ff)'}}>
          <circle cx="90" cy="90" r="85" fill="none" stroke="#00d4ff" strokeWidth="2" strokeDasharray="20 10" className="orb-circle">
            <animateTransform attributeName="transform" type="rotate" from="0 90 90" to="360 90 90" dur={ringSpeed} repeatCount="indefinite" />
          </circle>
          <circle cx="90" cy="90" r="65" fill="none" stroke="#00d4ff" strokeWidth="4" strokeDasharray="5 3" className="orb-circle">
            <animateTransform attributeName="transform" type="rotate" from="360 90 90" to="0 90 90" dur="6s" repeatCount="indefinite" />
          </circle>
          <circle cx="90" cy="90" r="45" fill="none" stroke="#00d4ff" strokeWidth="1" className="orb-circle">
            <animateTransform attributeName="transform" type="rotate" from="0 90 90" to="360 90 90" dur="4s" repeatCount="indefinite" />
          </circle>
          <circle cx="90" cy="90" r="30" fill="rgba(0,212,255,0.1)" />
          <text x="90" y="94" textAnchor="middle" fill="#00d4ff" fontSize="12" fontWeight="bold" letterSpacing="2">{orbText === 'SYSTEM ONLINE' ? 'JARVIS' : orbText}</text>
        </svg>
      </div>
    </div>
  );
}
