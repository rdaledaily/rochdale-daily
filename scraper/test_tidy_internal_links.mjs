// functions/_middleware.js tidyInternalHref: same-site .html links -> tidy URLs
// (Cloudflare Pages 308-redirects /x.html to /x). Run: node --test scraper/test_tidy_internal_links.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { tidyInternalHref as tidy } from '../functions/_middleware.js';

test('same-site .html links become tidy URLs', () => {
  assert.equal(tidy('/contact.html'), '/contact');
  assert.equal(tidy('/index.html'), '/');
  assert.equal(tidy('/weather/index.html'), '/weather/');
  assert.equal(tidy('/guides/banks-rochdale.html#open'), '/guides/banks-rochdale#open');
  assert.equal(tidy('/search.html?q=bins'), '/search?q=bins');
  assert.equal(tidy('https://rochdaledaily.co.uk/terms.html'), 'https://rochdaledaily.co.uk/terms');
  assert.equal(tidy('//www.rochdaledaily.co.uk/about.html'), '//www.rochdaledaily.co.uk/about');
});

test('everything else is left alone', () => {
  for (const href of ['https://example.com/a.html', 'mailto:news@rochdaledaily.co.uk', '/articles/x',
    'foo.html', '#top', '/news/', '/assets/x.htmlx', '', 'tel:01706']) {
    assert.equal(tidy(href), href);
  }
});
