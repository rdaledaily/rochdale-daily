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
console.log('Postcode crime accuracy checks passed (8 geo/metadata scenarios and local-list protections).');
