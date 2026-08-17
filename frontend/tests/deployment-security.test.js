import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


test("Compose defaults every host port to loopback", () => {
  const compose = readFileSync(
    new URL("../../docker-compose.yml", import.meta.url),
    "utf8",
  );
  assert.equal(
    compose.match(/\$\{NOVELFORGE_BIND_HOST:-127\.0\.0\.1\}:/g)?.length,
    2,
  );
  assert.match(compose, /"127\.0\.0\.1:11434:11434"/);
  assert.doesNotMatch(compose, /DEBUG:\s*"true"/);
  assert.match(
    compose,
    /ALLOW_INSECURE_NETWORK_EXPOSURE:\s*"\$\{ALLOW_INSECURE_NETWORK_EXPOSURE:-false\}"/,
  );
});


test("Nginx declares browser security headers", () => {
  const nginx = readFileSync(new URL("../nginx.conf", import.meta.url), "utf8");
  assert.match(nginx, /server_tokens off;/);
  for (const header of [
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Content-Security-Policy",
  ]) {
    assert.match(nginx, new RegExp(header));
  }
});
