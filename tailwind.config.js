/**
 * Build recipe for app/static/css/tailwind.css.
 *
 * The generated stylesheet is committed, so running docxy needs no Node and no
 * node_modules. Re-run this only after adding new Tailwind utility classes:
 *
 *   npx tailwindcss@3.4.17 -c tailwind.config.js \
 *     -i app/static/css/tailwind.src.css -o app/static/css/tailwind.css --minify
 *
 * Colour values point at the CSS custom properties defined in docxy.css, which
 * is what makes a single build serve both the light and dark themes.
 */
module.exports = {
  darkMode: "class",
  content: ["./app/static/**/*.html", "./app/static/js/*.js"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        fg: "var(--fg)",
        surface: "var(--surface)",
        surface2: "var(--surface-2)",
        muted: "var(--muted-fg)",
        line: "var(--border)",
        lineStrong: "var(--border-strong)",
        accent: "var(--accent)",
        accentText: "var(--accent-text)",
        ok: "var(--ok)",
        warn: "var(--warn)",
        danger: "var(--danger)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      maxWidth: { prose: "68ch" },
    },
  },
};
