/** Small line illustrations for the "How it works" cards, drawn in the garden palette. */

const frame = "h-28 w-full rounded-xl border border-white/5 bg-night/60";

export function TalkIllustration() {
  const bars = [6, 14, 24, 34, 22, 40, 28, 16, 30, 44, 26, 12, 20, 8];
  return (
    <svg viewBox="0 0 240 112" className={frame} aria-hidden>
      <circle cx="44" cy="56" r="20" fill="var(--dusk)" stroke="var(--glow)" strokeOpacity="0.5" />
      <path
        d="M38 50h12M38 56h8M38 62h10"
        stroke="var(--glow)"
        strokeWidth="2"
        strokeLinecap="round"
      />
      {bars.map((h, i) => (
        <rect
          key={i}
          x={84 + i * 10}
          y={56 - h / 2}
          width="5"
          height={h}
          rx="2.5"
          fill={i % 3 === 0 ? "var(--moss)" : "var(--glow)"}
          opacity={0.35 + (h / 44) * 0.65}
        />
      ))}
    </svg>
  );
}

export function ProveIllustration() {
  return (
    <svg viewBox="0 0 240 112" className={frame} aria-hidden>
      <rect x="28" y="22" width="120" height="68" rx="10" fill="var(--dusk)" />
      <path
        d="M44 40h70M44 54h88M44 68h56"
        stroke="#e8ecf6"
        strokeOpacity="0.35"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <rect
        x="160"
        y="30"
        width="56"
        height="22"
        rx="11"
        fill="var(--moss)"
        fillOpacity="0.2"
        stroke="var(--moss)"
      />
      <path
        d="m172 41 5 5 10-10"
        stroke="var(--moss)"
        strokeWidth="2.4"
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <rect
        x="160"
        y="60"
        width="56"
        height="22"
        rx="11"
        fill="var(--bloom)"
        fillOpacity="0.12"
        stroke="var(--bloom)"
        strokeOpacity="0.6"
      />
      <text x="188" y="75" textAnchor="middle" fontSize="10" fill="var(--bloom)">
        assisted
      </text>
    </svg>
  );
}

export function GrowIllustration() {
  return (
    <svg viewBox="0 0 240 112" className={frame} aria-hidden>
      <path d="M20 92h200" stroke="#e8ecf6" strokeOpacity="0.15" strokeWidth="2" />
      {[0, 1, 2, 3].map((stage) => {
        const x = 46 + stage * 50;
        const h = 14 + stage * 12;
        return (
          <g key={stage}>
            <path
              d={`M${x} 92V${92 - h}`}
              stroke="var(--moss)"
              strokeWidth="2.5"
              strokeLinecap="round"
            />
            <ellipse
              cx={x - 7}
              cy={92 - h + 4}
              rx={6 + stage * 2}
              ry={3 + stage}
              fill="var(--moss)"
              transform={`rotate(-30 ${x - 7} ${92 - h + 4})`}
            />
            <ellipse
              cx={x + 7}
              cy={92 - h + 2}
              rx={6 + stage * 2}
              ry={3 + stage}
              fill="var(--glow)"
              opacity="0.8"
              transform={`rotate(30 ${x + 7} ${92 - h + 2})`}
            />
            {stage === 3 && <circle cx={x} cy={92 - h - 6} r="5" fill="var(--bloom)" />}
          </g>
        );
      })}
    </svg>
  );
}

export function RetainIllustration() {
  const days = Array.from({ length: 14 }, (_, i) => i);
  const reviewed = new Set([0, 1, 3, 6, 10, 13]);
  return (
    <svg viewBox="0 0 240 112" className={frame} aria-hidden>
      {days.map((d) => (
        <rect
          key={d}
          x={30 + (d % 7) * 26}
          y={26 + Math.floor(d / 7) * 34}
          width="18"
          height="18"
          rx="5"
          fill={reviewed.has(d) ? "var(--moss)" : "var(--dusk)"}
          opacity={reviewed.has(d) ? 0.9 : 1}
        />
      ))}
      <circle cx="214" cy="35" r="9" fill="var(--bloom)" opacity="0.9" />
      <path d="M210 35h8M214 31v8" stroke="var(--night)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
