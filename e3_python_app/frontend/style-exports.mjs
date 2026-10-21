/** Read the upstream Sass :export contract used by AV2's non-hashed styles. */
export function scssExports(css) {
  const result = {};
  for (const block of css.matchAll(/:export\s*\{([^}]+)\}/g)) {
    for (const declaration of block[1].split(";")) {
      const colon = declaration.indexOf(":");
      if (colon > 0) {
        result[declaration.slice(0, colon).trim()] = declaration.slice(colon + 1).trim().replace(/^['"]|['"]$/g, "");
      }
    }
  }
  return result;
}
