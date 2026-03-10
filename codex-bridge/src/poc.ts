import { Codex } from "@openai/codex-sdk";

async function main() {
  const prompt =
    process.env.CODEX_POC_PROMPT?.trim() ||
    "Reply with exactly: codex sdk poc ok";

  const codex = new Codex();
  const thread = codex.startThread();
  const result = await thread.run(prompt);
  const output = typeof result.finalResponse === "string" ? result.finalResponse.trim() : "";

  if (!output) {
    throw new Error("Codex SDK POC returned empty output");
  }

  process.stdout.write(`${output}\n`);
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`Codex SDK POC failed: ${message}\n`);
  process.exitCode = 1;
});
