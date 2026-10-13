/* Regression guard for postcode-local crime editorial relevance.
 * The browser dashboard may only show a report as nearby when the story
 * carries verified incident coordinates within one mile.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const text = fs.readFileSync('assets/js/my-rochdale.js', 'utf8');
const start = text.indexOf('const CRIME_RADIUS_KM=');
const end = text.indexOf('\nfunction match(s)', start);
assert.ok(start >= 0 && end > start, 'Postcode crime radius check is present');
const context = vm.createContext({
 archiveUrl: x => /^\/articles\/[a-z0-9-]+\.html$/i.test(x.url || ''),
});
vm.runInContext(text.slice(start, end) + '\nthis.check = verifiedNearbyCrime;', context);
const check = context.check;
const postcode = { latitude: 53.617, longitude: -2.153 };
const article = {
 category: 'Crime', url: '/articles/verified-crime.html',
 incident_verified: true, incident_latitude: 53.620, incident_longitude: -2.152
};
assert.equal(check(article, postcode), true, 'Verified incident near a postcode should display');
assert.equal(check({ ...article, incident_latitude: 53.650, incident_longitude: -2.100 }, postcode), false, 'Incident in a different area must not display');
assert.equal(check({ ...article, incident_verified: false }, postcode), false, 'Unverified coordinates must not display');
assert.equal(check({ ...article, incident_verified: undefined }, postcode), false, 'Ward or town mentions cannot count as verified');
assert.equal(check({ category:'Crime', url:article.url, title:'Crime in Rochdale' }, postcode), false, 'A town-only headline is not local evidence');
assert.equal(check({ ...article, incident_latitude: null }, postcode), false, 'Missing coordinates must not become 0,0');
assert.equal(check({ ...article, incident_latitude: '53.620' }, postcode), false, 'Unreviewed coordinates stored as strings should not pass');
assert.equal(check({ ...article, category: 'Community' }, postcode), false, 'Noncrime stories cannot become incidents');
assert.match(text, /if\(active==="local"\)entries=entries\.filter\(/, 'Local news list must also apply exact crime gating');
assert.match(text, /No crime articles in our available archive have a verified incident location within one mile/, 'No-data state must be explicit');
assert.doesNotMatch(text, /const tooBroad=new Set/, 'Old ward-level crime matching must not be restored');

// Official police priorities must be matched to the SAME ward, not a
// neighbouring ward, and must never be presented as postcode incident counts.
const priorityData = JSON.parse(fs.readFileSync('assets/data/gmp-ward-policing-priorities.json', 'utf8'));
const keys = Object.keys(priorityData.wards);
assert.ok(keys.length >= 7, 'Official GMP priorities available for multiple wards');
assert.ok(keys.every(w => priorityData.wards[w].url.startsWith('https://www.gmp.police.uk/')), 'Every policing priority cites GMP');
assert.ok(keys.every(w => /^2026-\d\d-\d\d$/.test(priorityData.wards[w].updated)), 'Every priority has its own updated date');
assert.notEqual(priorityData.wards['Central Rochdale'], priorityData.wards['Spotland and Falinge'], 'Separate police teams are never interchangeable');
const census = JSON.parse(fs.readFileSync('assets/data/gmp-postcode-district-crime.json','utf8'));
assert.equal(census.status,'verification_pending','Ambiguous GMP FOI numbers are not yet safe to publish');
assert.equal(Object.keys(census.districts).length,0,'No unsupported postcode district crime count is exposed');
assert.match(text,/data\.wards\?\.\[expectedWard\]/,'GMP team is looked up using the exact selected ward');
assert.match(text,/No alternative neighbourhood information has been substituted/,'Source failures must not show other areas');

console.log('Postcode crime accuracy checks passed (8 geo/metadata scenarios and local-list protections).');
