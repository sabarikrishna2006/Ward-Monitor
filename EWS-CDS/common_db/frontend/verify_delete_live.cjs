/**
 * Runtime verification: optimistic delete
 */
const http = require('http');
const fs   = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const FRONT_DIR   = __dirname;
const STATIC_PORT = 19993;
const MOCK_PORT   = 19992;

// Static server with config.js override
const staticServer = http.createServer((req, res) => {
  const reqPath = req.url.split('?')[0];
  if (reqPath === '/config.js' || reqPath.endsWith('/config.js')) {
    res.writeHead(200, {'Content-Type':'application/javascript'});
    res.end(`
window.FOQAL_CONFIG = { API_PORT:${MOCK_PORT}, DATA_PORT:${MOCK_PORT}, WARD_PORT:${MOCK_PORT} };
const _h = location.hostname;
window.FOQAL_API_BASE  = 'http://' + _h + ':${MOCK_PORT}';
window.FOQAL_DATA_BASE = 'http://' + _h + ':${MOCK_PORT}';
    `);
    return;
  }
  const filePath = path.join(FRONT_DIR, reqPath === '/' ? '/upload.html' : reqPath);
  if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
    res.writeHead(404); res.end(); return;
  }
  const mime = {'.html':'text/html','.js':'application/javascript','.css':'text/css'}[path.extname(filePath)] || 'text/plain';
  res.writeHead(200, {'Content-Type': mime});
  res.end(fs.readFileSync(filePath));
});

// Mock API server
let deleteIntercepted = false;

const MOCK_FILES = [{ id:42, file_id:42, file_name:'pharmacy_test.csv', file_type:'pharmacy', upload_date:'2026-06-22T10:00:00Z' }];

const mockServer = http.createServer(async (req, res) => {
  const url = req.url, method = req.method;
  res.setHeader('Content-Type','application/json');
  res.setHeader('Access-Control-Allow-Origin','*');
  res.setHeader('Access-Control-Allow-Methods','GET,POST,PUT,DELETE,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers','Content-Type,Authorization');

  if (method==='OPTIONS') { res.writeHead(204); res.end(); return; }

  const reply = o => { res.writeHead(200); res.end(JSON.stringify(o)); };

  if (url.includes('/api/me') || url.includes('/api/auth')) return reply({id:'u1',full_name:'Test User',email:'t@t.com',role:'resident'});
  if (url.includes('/uploaded_clinical_data')) return reply({pharmacy:[{drug:'Metoprolol',dose:'50mg'},{drug:'Lisinopril',dose:'10mg'}]});
  if (url.includes('/revision_state')) return reply({enc_status:'Pending Ingestion'});
  if (url.match(/\/files($|\?|&)/)) return reply({files: MOCK_FILES});
  if (url.includes('/encounter')) return reply({id:20553493, hadm_id:20553493, status:'Pending Ingestion',diagnosis:'Dilated Cardiomyopathy',admission_type:'EMERGENCY',admit_time:'2026-01-01T00:00:00Z',encounter_id:20553493});
  if (method==='DELETE' && url.includes('/uploaded_files/42')) {
    deleteIntercepted = true;
    console.log('[MOCK] DELETE /uploaded_files/42 — 800ms delay');
    await new Promise(r => setTimeout(r,800));
    return reply({status:'ok',deleted_file_id:'42'});
  }
  if (url.includes('/tab/') || url.includes('/display')) return reply({pharmacy:[],prescriptions:[],labevents:[],chartevents:[]});
  reply({});
});

async function run() {
  await new Promise(r => staticServer.listen(STATIC_PORT, r));
  await new Promise(r => mockServer.listen(MOCK_PORT, r));
  console.log(`Static  → http://localhost:${STATIC_PORT}`);
  console.log(`Mock API→ http://localhost:${MOCK_PORT}`);

  const browser = await chromium.launch({ headless: true, args: ['--disable-web-security'] });
  const ctx     = await browser.newContext({
    viewport: {width:1400,height:900},
    ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();

  // Verbose logging
  page.on('console', m => console.log(`[PAGE ${m.type()}] ${m.text().slice(0,200)}`));
  page.on('pageerror', e => console.log('[PAGEERROR]', e.message.slice(0,200)));
  page.on('request', r => {
    if (!r.url().includes(`localhost:${STATIC_PORT}`)) console.log('[REQ]', r.method(), r.url().replace(/.*localhost:\d+/, ''));
  });
  page.on('requestfailed', r => console.log('[FAIL]', r.url().replace(/.*localhost:\d+/,'')));

  // Seed sessionStorage — auth guard (line 222) checks foqal_user.email
  await page.addInitScript((hadm) => {
    sessionStorage.setItem('foqal_user', JSON.stringify({
      email:'test@hospital.com', full_name:'Test User', role:'resident'
    }));
    sessionStorage.setItem('foqal_token','fake-jwt');
    sessionStorage.setItem('foqal_hadm', String(hadm));
    sessionStorage.setItem(`foqal_hasDCM_${hadm}`,'1');
    sessionStorage.setItem('foqal_patient_preview', JSON.stringify({
      hadm_id:hadm, status:'Pending Ingestion', _name:'Priya Sharma',
      _age:52, _gender:'M', _diagnosis:'Dilated Cardiomyopathy',
      primary_diagnosis_title:'Dilated Cardiomyopathy'
    }));
  }, 20553493);

  // Use 'commit' — does NOT wait for scripts, just for HTTP response headers
  console.log('Navigating (commit)…');
  await page.goto(`http://localhost:${STATIC_PORT}/upload.html`, {
    waitUntil: 'commit', timeout: 10000
  });
  console.log('HTTP response committed.');

  // Wait for the render engine to settle
  await page.waitForTimeout(4000);
  console.log('4s wait done.');

  await page.screenshot({path:'verify_01_initial.png'});
  console.log('Screenshot 01: verify_01_initial.png');

  // Inspect page state
  const title = await page.title().catch(()=>'?');
  console.log('Page title:', title);
  const url   = page.url();
  console.log('Page URL:', url);

  // Check if redirected away from upload.html
  if (!url.includes('upload.html') && !url.includes(`localhost:${STATIC_PORT}`)) {
    console.log('FAIL: page redirected to', url);
    await browser.close(); staticServer.close(); mockServer.close(); process.exit(1);
  }

  // Dump visible text for debugging
  const bodyText = await page.locator('body').innerText().catch(()=>'(error reading body)');
  console.log('\n--- Body text (first 800 chars) ---');
  console.log(bodyText.slice(0,800));
  console.log('---');

  // ── Navigate to Uploaded Files tab ───────────────────────────────────────
  const uploadedTab = page.locator('text=Uploaded Files').first();
  if (await uploadedTab.count()) {
    await uploadedTab.click();
    await page.waitForTimeout(400);
  }

  await page.screenshot({path:'verify_02_uploaded_tab.png'});
  console.log('Screenshot 02: verify_02_uploaded_tab.png');

  const rowsBefore  = await page.locator('table.tbl tbody tr').count();
  const delBtnCount = await page.locator('button:has-text("Delete")').count();
  console.log(`Rows: ${rowsBefore}, Delete buttons: ${delBtnCount}`);

  if (delBtnCount === 0) {
    console.log('FAIL: No Delete button. Saving HTML dump…');
    fs.writeFileSync('verify_page.html', await page.content());
    await browser.close(); staticServer.close(); mockServer.close(); process.exit(1);
  }

  // Fire-and-forget click → screenshot 120ms later
  const delBtn = page.locator('button:has-text("Delete")').first();
  delBtn.click();
  await page.waitForTimeout(120);

  await page.screenshot({path:'verify_03_optimistic.png'});
  console.log('Screenshot 03 (120ms after click): verify_03_optimistic.png');

  const rowsOptimistic = await page.locator('table.tbl tbody tr').count();
  console.log(`Rows 120ms after click: ${rowsOptimistic} (was ${rowsBefore})`);

  // Wait for server to respond (800ms mock delay)
  await page.waitForTimeout(1100);
  await page.screenshot({path:'verify_04_server_done.png'});
  const rowsAfterServer = await page.locator('table.tbl tbody tr').count();
  console.log(`Rows after server confirms: ${rowsAfterServer}`);
  console.log('Screenshot 04: verify_04_server_done.png');

  // Verdict
  const pass = deleteIntercepted && rowsOptimistic < rowsBefore;
  console.log(`\n${'═'.repeat(50)}`);
  console.log(`  Before: ${rowsBefore} rows | 120ms after click: ${rowsOptimistic} | DELETE hit: ${deleteIntercepted}`);
  console.log(`  VERDICT: ${pass ? '✅ PASS' : '❌ FAIL'}`);

  await browser.close();
  staticServer.close(); mockServer.close();
  process.exit(pass ? 0 : 1);
}

run().catch(err => {
  console.error('Fatal:', err.message);
  staticServer.close(); mockServer.close(); process.exit(1);
});
