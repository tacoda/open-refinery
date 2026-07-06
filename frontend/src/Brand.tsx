// Open Refinery brand mark — "a dark factory with the lights on".
// A left→right process graph: work flows through governed steps; the final
// output node is lit (purple glow) — legible automation, the light switched on.
// Purely geometric, crisp at any size. `currentColor` = the dim (dark) nodes;
// the accent is the lit output.

const ACCENT = '#7c3aed' // matches the app's purple primary

export function LogoMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none"
         xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <filter id="or-glow" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="1.6" result="b" />
          <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>
      {/* links between steps */}
      <path d="M9 16 H15 M17 16 H23" stroke="currentColor" strokeWidth="1.6"
            strokeLinecap="round" opacity="0.55" />
      {/* two dim upstream steps */}
      <circle cx="7" cy="16" r="3" stroke="currentColor" strokeWidth="1.6" opacity="0.7" />
      <circle cx="16" cy="16" r="3" stroke="currentColor" strokeWidth="1.6" opacity="0.85" />
      {/* the lit output — the light on */}
      <circle cx="25" cy="16" r="3.4" fill={ACCENT} filter="url(#or-glow)" />
      <circle cx="25" cy="16" r="1.2" fill="#fff" opacity="0.9" />
    </svg>
  )
}

export function Brand({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <span className={`brand-lockup ${className}`}>
      <LogoMark size={size} />
      <span className="brand-word">Open&nbsp;Refinery</span>
    </span>
  )
}
