import assert from "node:assert/strict";
import path from "node:path";

import vue from "@vitejs/plugin-vue";
import { rollup } from "rollup";

const aliases = new Map([
  ["vue", "vue/dist/vue.runtime.esm-bundler.js"],
  ["@vue/runtime-dom", "@vue/runtime-dom/dist/runtime-dom.esm-bundler.js"],
  ["@vue/runtime-core", "@vue/runtime-core/dist/runtime-core.esm-bundler.js"],
  ["@vue/reactivity", "@vue/reactivity/dist/reactivity.esm-bundler.js"],
  ["@vue/shared", "@vue/shared/dist/shared.esm-bundler.js"],
]);

const resolveVuePackages = {
  name: "resolve-vue-packages",
  resolveId(source) {
    const target = aliases.get(source);
    return target ? path.resolve("node_modules", target) : null;
  },
};

const verifyCss = {
  name: "verify-css",
  transform(_code, id) {
    if (id.endsWith(".css")) {
      return { code: "export default undefined;", map: null };
    }
    return null;
  },
};

const bundle = await rollup({
  input: "src/main.js",
  plugins: [resolveVuePackages, vue(), verifyCss],
});
const { output } = await bundle.generate({ format: "es" });
await bundle.close();

const chunks = output.filter((item) => item.type === "chunk");
assert.equal(chunks.length, 1);
assert.match(chunks[0].code, /NovelForge/);
assert.ok(chunks[0].code.length > 100_000);
console.log(`Vue bundle verification passed (${chunks[0].code.length} bytes).`);
