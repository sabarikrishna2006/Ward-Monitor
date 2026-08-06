const fs = require('fs');

const htmlContent = fs.readFileSync('e:/IP_EarlyWarning/EWS-CDS/foqal_careos_unified_erd_final.html', 'utf8');

// We need to extract the JS objects: HC_TABLES, EWS_TABLES, DAI_TABLES, MIMIC_TABLES
// Let's just create a JS file that defines them and then exports them.

const scriptContent = htmlContent.substring(htmlContent.indexOf('const C ='), htmlContent.indexOf('function renderTables'));

const execScript = `
${scriptContent}

function generateErDiagram(tables) {
  let er = "erDiagram\\n";
  for (const [name, def] of Object.entries(tables)) {
    er += \`    \${name} {\\n\`;
    for (const c of def.cols) {
      let typeStr = (c.type || 'string').replace(/ /g, '_');
      let nameStr = c.name || 'id';
      let keyStr = c.key ? \` \${c.key}\` : '';
      let commentStr = c.desc ? \` "\${c.desc.replace(/"/g, "'")}"\` : (c.nullable ? \` "nullable"\` : "");
      er += \`        \${typeStr} \${nameStr}\${keyStr}\${commentStr}\\n\`;
    }
    er += \`    }\\n\`;
  }
  return er;
}

console.log("--- HC ---");
console.log(generateErDiagram(HC_TABLES));
console.log("--- EWS ---");
console.log(generateErDiagram(EWS_TABLES));
console.log("--- DAI ---");
console.log(generateErDiagram({...DAI_TABLES, ...MIMIC_TABLES}));
`;

fs.writeFileSync('e:/IP_EarlyWarning/EWS-CDS/temp_exec.js', execScript);
console.log("Created temp_exec.js");
