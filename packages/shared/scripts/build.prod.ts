import { Template } from "e2b";
import { template } from "./template.js";

async function main() {
  await Template.build(template, {
    alias: "test1",
    cpuCount: 2,
    memoryMB: 2048,
    skipCache: true,
    onBuildLogs: (it) => console.log(it.toString()),
  });
}

main().catch((err) => console.error(err));
