// Hand-written, minimal inline SVG icons -- no icon library dependency.
// Each is a 20x20 outline glyph matching the sidebar's text colour via
// `currentColor`, so active/hover states just work with existing classes.

type IconProps = { className?: string };

const base = 'h-5 w-5 flex-shrink-0';

export function IconDashboard({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <rect x="2.5" y="2.5" width="6" height="6" rx="1" />
      <rect x="11.5" y="2.5" width="6" height="6" rx="1" />
      <rect x="2.5" y="11.5" width="6" height="6" rx="1" />
      <rect x="11.5" y="11.5" width="6" height="6" rx="1" />
    </svg>
  );
}

export function IconBook({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M3 4.5c0-1 .8-1.5 2-1.5h5v13H5c-1.2 0-2 .5-2 1.5z" />
      <path d="M17 4.5c0-1-.8-1.5-2-1.5h-5v13h5c1.2 0 2 .5 2 1.5z" />
    </svg>
  );
}

export function IconFacts({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <circle cx="10" cy="10" r="7.5" />
      <path d="M10 6.5v4l2.5 1.5" strokeLinecap="round" />
    </svg>
  );
}

export function IconTerminology({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M3 5h10M3 10h14M3 15h7" strokeLinecap="round" />
    </svg>
  );
}

export function IconShield({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M10 2.5 16.5 5v5c0 4-2.8 6.6-6.5 7.5C6.3 16.6 3.5 14 3.5 10V5z" />
    </svg>
  );
}

export function IconSwatch({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <rect x="2.5" y="4.5" width="5" height="12" rx="1" />
      <rect x="8.5" y="7" width="5" height="9.5" rx="1" transform="rotate(-18 11 11.75)" />
    </svg>
  );
}

export function IconSubmissions({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M5 2.5h7l3 3V17a.5.5 0 0 1-.5.5H5.5A.5.5 0 0 1 5 17z" />
      <path d="M12 2.5V5.5a.5.5 0 0 0 .5.5H15.5" />
      <path d="M7 10h6M7 13h6" strokeLinecap="round" />
    </svg>
  );
}

export function IconChart({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M3 17V3M3 17h14" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6.5 14v-4M10.5 14V7M14.5 14v-6" strokeLinecap="round" />
    </svg>
  );
}

export function IconMenu({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M3 5h14M3 10h14M3 15h14" strokeLinecap="round" />
    </svg>
  );
}

export function IconClose({ className = base }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M5 5l10 10M15 5 5 15" strokeLinecap="round" />
    </svg>
  );
}
