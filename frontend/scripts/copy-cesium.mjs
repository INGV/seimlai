import { cp, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
for (const name of ["Assets", "ThirdParty", "Widgets", "Workers"]) {
  const target = new URL(`public/cesium/${name}`, root);
  await mkdir(target, { recursive: true });
  await cp(
    fileURLToPath(new URL(`node_modules/cesium/Build/Cesium/${name}`, root)),
    fileURLToPath(target),
    { recursive: true },
  );
}
