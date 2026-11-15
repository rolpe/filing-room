// Line icons from the mockups, as an inline SVG sprite rendered once by the shell.
const SYMBOLS: Record<string, string> = {
  logo: '<path d="M5 4.5h9l5 5V19.5H5z"/><path d="M14 4.5v5h5"/><path d="M8.5 14h7M8.5 17h4.5"/>',
  list: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  usage: '<path d="M4 19.5h16"/><path d="M7 16v-5M12 16V6.5M17 16v-8"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  check: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.2 2.4 2.4 4.6-5"/>',
  flag: '<path d="M6 20.5V4.5"/><path d="M6 5h11l-2.2 3.8L17 12.5H6"/>',
  none: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
  down: '<path d="M12 4.5v10.5M7.5 11l4.5 4.5 4.5-4.5M5 19.5h14"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  dn: '<path d="m6 9 6 6 6-6"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  ext: '<path d="M13.5 5H19v5.5M19 5l-8 8"/><path d="M17 14v4.5H5.5V7H10"/>',
  copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
  note: '<path d="M5 19l1-4L16.5 4.5l3 3L9 18z"/><path d="M14.5 6.5l3 3"/>',
  ask: '<path d="M5 5.5h14v10.5h-8l-4 3.5V16H5z"/>',
  more: '<circle cx="6" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="18" cy="12" r="1"/>',
  alert: '<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17v.01"/>',
  play: '<path d="M8 5.5v13l10-6.5z"/>',
  trash: '<path d="M5 7h14M10 7V5h4v2M7 7l1 12.5h8L17 7"/>',
  print: '<path d="M7 9V4.5h10V9"/><rect x="4.5" y="9" width="15" height="7.5" rx="1.5"/><path d="M7.5 14h9v5.5h-9z"/>',
  gauge: '<path d="M4.5 16.5a7.5 7.5 0 1 1 15 0"/><path d="m12 16.5 3.5-4.5"/><path d="M4.5 19.5h15"/>',
  undo: '<path d="M9 7 4.5 11.5 9 16"/><path d="M5 11.5h9a5 5 0 0 1 0 10h-2"/>',
};

export function IconSprite() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <defs dangerouslySetInnerHTML={{
        __html: Object.entries(SYMBOLS).map(([id, d]) => `<symbol id="i-${id}" viewBox="0 0 24 24">${d}</symbol>`).join(""),
      }} />
    </svg>
  );
}

export function Icon({ name, className = "icon" }: { name: keyof typeof SYMBOLS | string; className?: string }) {
  return (
    <svg className={className} aria-hidden="true">
      <use href={`#i-${name}`} />
    </svg>
  );
}
