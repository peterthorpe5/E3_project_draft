import { test } from "node:test";
import assert from "node:assert/strict";
import { scssExports } from "./style-exports.mjs";
test("AV2 Sass exports preserve colours, class names and numerical values", () => {
  assert.deepEqual(scssExports(':export { colour: "#123456"; size: 5; name: resi_q; } :export { other: x; }'),
    { colour: "#123456", size: "5", name: "resi_q", other: "x" });
  assert.deepEqual(scssExports(".some-class { color: red; }"), {});
});
