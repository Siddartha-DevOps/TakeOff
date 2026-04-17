import React, { useState, useEffect } from 'react';
import { SAMPLE_DETECTION, getRoomColor } from '../mock/mockAI';

// Animated floor plan canvas used in Hero. Rooms/doors/windows appear in sequence.
export default function FloorPlanCanvas({ autoplay = true, showLabels = true, compact = false }) {
  const [stage, setStage] = useState(0);

  useEffect(() => {
    if (!autoplay) return;
    const tid = setInterval(() => setStage((s) => (s + 1) % 5), 1400);
    return () => clearInterval(tid);
  }, [autoplay]);

  const { rooms, doors, windows } = SAMPLE_DETECTION;
  const viewBox = compact ? '0 0 800 680' : '0 0 800 680';

  return (
    <div className="relative w-full h-full">
      <svg viewBox={viewBox} className="w-full h-full" preserveAspectRatio="xMidYMid meet">
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#e2e8f0" strokeWidth="0.5" />
          </pattern>
          <pattern id="gridLg" width="160" height="160" patternUnits="userSpaceOnUse">
            <path d="M 160 0 L 0 0 0 160" fill="none" stroke="#cbd5e1" strokeWidth="0.8" />
          </pattern>
        </defs>

        {/* Background grid */}
        <rect width="800" height="680" fill="#fafbff" />
        <rect width="800" height="680" fill="url(#grid)" />
        <rect width="800" height="680" fill="url(#gridLg)" />

        {/* Outer walls */}
        <g stroke="#0f172a" strokeWidth="4" fill="none">
          <rect x="60" y="60" width="660" height="560" rx="1" />
        </g>

        {/* Interior walls */}
        <g stroke="#1e293b" strokeWidth="2" fill="none">
          <line x1="300" y1="60" x2="300" y2="200" />
          <line x1="60" y1="200" x2="300" y2="200" />
          <line x1="260" y1="200" x2="260" y2="440" />
          <line x1="340" y1="200" x2="340" y2="440" />
          <line x1="340" y1="340" x2="720" y2="340" />
          <line x1="560" y1="200" x2="560" y2="440" />
          <line x1="60" y1="370" x2="260" y2="370" />
          <line x1="340" y1="440" x2="720" y2="440" />
          <line x1="340" y1="600" x2="560" y2="600" />
          <line x1="260" y1="510" x2="340" y2="510" />
        </g>

        {/* Room fills */}
        <g opacity={stage >= 1 ? 0.22 : 0}>
          {rooms.map((r, i) => {
            const [x1, y1, x2, y2] = r.bbox;
            return (
              <rect
                key={r.id}
                x={x1 + 3} y={y1 + 3} width={x2 - x1 - 6} height={y2 - y1 - 6}
                fill={getRoomColor(r.label)}
                style={{ transition: 'opacity 600ms ease', transitionDelay: `${i * 80}ms` }}
              />
            );
          })}
        </g>

        {/* Room labels */}
        {showLabels && (
          <g opacity={stage >= 2 ? 1 : 0} style={{ transition: 'opacity 500ms ease' }}>
            {rooms.map((r) => {
              const [x1, y1, x2, y2] = r.bbox;
              const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
              return (
                <g key={`lbl-${r.id}`} transform={`translate(${cx}, ${cy})`}>
                  <text textAnchor="middle" className="text-[12px]" fontSize="12" fontWeight="600" fill="#1e293b">{r.label}</text>
                  <text y="14" textAnchor="middle" fontSize="9" fill="#64748b" fontFamily="JetBrains Mono, monospace">{r.area} sf</text>
                </g>
              );
            })}
          </g>
        )}

        {/* Doors */}
        <g opacity={stage >= 3 ? 1 : 0} style={{ transition: 'opacity 400ms ease' }}>
          {doors.map((d, i) => (
            <g key={d.id} transform={`translate(${d.x},${d.y}) rotate(${d.rotation || 0})`}>
              <rect x="-2" y="-14" width="4" height="28" fill="#fff" />
              <path d={`M 0 -14 A ${d.width} ${d.width} 0 0 1 ${d.width} 14`} stroke="#06b6d4" strokeWidth="1.5" fill="none"
                style={{ animation: stage >= 3 ? `fade-in 400ms ease ${i * 40}ms both` : 'none' }} />
              <circle cx="0" cy="-14" r="3" fill="#06b6d4" />
            </g>
          ))}
        </g>

        {/* Windows */}
        <g opacity={stage >= 3 ? 1 : 0} style={{ transition: 'opacity 400ms ease' }}>
          {windows.map((w) => (
            <g key={w.id} transform={`translate(${w.x},${w.y}) rotate(${w.rotation || 0})`}>
              <rect x="0" y="-3" width={w.width} height="6" fill="#fbbf24" stroke="#d97706" strokeWidth="1" />
              <line x1="0" y1="0" x2={w.width} y2="0" stroke="#fff" strokeWidth="1" />
            </g>
          ))}
        </g>

        {/* Scanning line */}
        <g opacity={stage === 4 ? 1 : 0}>
          <line x1="60" x2="720" y1="340" y2="340" stroke="#4f46e5" strokeWidth="1" strokeDasharray="4 4" />
        </g>
      </svg>
    </div>
  );
}

