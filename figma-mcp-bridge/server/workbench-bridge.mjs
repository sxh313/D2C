// Keep the upstream stdio server alive for the lifetime of the workbench.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const server = fileURLToPath(new URL('./dist/index.js', import.meta.url));
const child = spawn(process.execPath, [server], {
  cwd: fileURLToPath(new URL('.', import.meta.url)),
  stdio: ['pipe', 'ignore', 'inherit'],
  env: { ...process.env, FIGMA_BRIDGE_HOST: '127.0.0.1', FIGMA_BRIDGE_PORT: '1994' },
  windowsHide: true,
});
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill());
