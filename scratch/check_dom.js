const { spawn } = require('child_process');
const os = require('os');

const edge = spawn('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  '--no-default-browser-check',
  '--disable-search-engine-choice-screen',
  '--remote-debugging-port=9223',
  '--user-data-dir=' + os.tmpdir() + '/edge_test_' + Date.now(),
  'http://127.0.0.1:8000/#maximized'
]);

setTimeout(async () => {
  try {
    const list = await (await fetch('http://127.0.0.1:9223/json')).json();
    const target = list.find(t => t.url.includes('127.0.0.1:8000')) || list[0];
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    ws.addEventListener('open', () => {
      ws.send(JSON.stringify({ id: 1, method: 'Runtime.enable' }));
      ws.send(JSON.stringify({ id: 2, method: 'Log.enable' }));
      ws.send(JSON.stringify({
        id: 3,
        method: 'Runtime.evaluate',
        params: {
          expression: `(async () => {
            await loadAuditTable('2025');
            return {
              rows: document.getElementById('auditTableBody')?.children?.length,
              sample: document.getElementById('auditTableBody')?.children[0]?.innerHTML
            };
          })()`,
          awaitPromise: true,
          returnByValue: true
        }
      }));
    });
    ws.addEventListener('message', e => {
      const msg = JSON.parse(e.data);
      if (msg.method === 'Runtime.consoleAPICalled' || msg.method === 'Runtime.exceptionThrown') {
        console.log('CONSOLE:', JSON.stringify(msg));
      }
      if (msg.id === 3) {
        console.log('EVAL RESULT:', JSON.stringify(msg.result));
        ws.close();
        edge.kill();
        process.exit(0);
      }
    });
  } catch (err) {
    console.error('ERROR:', err);
    edge.kill();
    process.exit(1);
  }
}, 2500);
